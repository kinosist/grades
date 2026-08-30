import json
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse  
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.middleware.csrf import get_token
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.urls import reverse
from ...models import CustomUser, Student, ClassRoom, StudentClassPoints, ClassRoomEnrollment, TeacherStudentAssignment

@login_required
def student_edit_view(request, student_number):
    """学生編集"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    cleaned_student_number = Student.clean_student_number(student_number)
    student = get_object_or_404(CustomUser, student_number=cleaned_student_number, role='student')

    csrf_token = get_token(request)
    
    if request.method == 'POST':
        # フォームデータの取得
        full_name = request.POST.get('full_name')
        furigana = request.POST.get('furigana')
        email = request.POST.get('email')
        memo = request.POST.get('memo', '')

        # バリデーション
        cleaned_email = Student.clean_email(email)
        if not full_name or not furigana or not cleaned_email:
            messages.error(request, '氏名・ふりがな・メールアドレスは必須項目です。')
        else:
            try:
                # メールアドレスの重複チェック（正規化は上で実施済み）
                other_student = Student.objects.filter(role='student', email=cleaned_email).exclude(id=student.id).first()
                if other_student:
                    messages.error(request, f'メールアドレス "{cleaned_email}" は、既に別の学生（学籍番号: {other_student.student_number}）に使用されています。')
                    return render(request, 'school_management/student_edit.html', {
                        'student': student,
                        'csrf_token': csrf_token,
                    })

                # 学生情報を更新
                student.full_name = full_name
                student.furigana = furigana
                student.email = cleaned_email
                student.memo = memo

                student.save()
                messages.success(request, f'{student.full_name}さんの情報を更新しました。')
                return redirect('school_management:student_detail', student_number=student.student_number)
                
            except Exception as e:
                messages.error(request, f'更新中にエラーが発生しました: {str(e)}')
    
    context = {
        'student': student,
        'csrf_token': csrf_token,
    }
    return render(request, 'school_management/student_edit.html', context)

@login_required
def student_create_view(request):
    """学生作成（単体・一括対応）"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    csrf_token = get_token(request)
    
    # クラス情報の取得（パラメータがある場合）
    classroom_id = request.GET.get('classroom_id') or request.POST.get('classroom_id')
    classroom = None
    if classroom_id:
        classroom = get_object_or_404(ClassRoom, id=classroom_id, teachers=request.user)

    if request.method == 'POST':
        registration_type = request.POST.get('registration_type', 'single')
        
        if registration_type == 'bulk':
            # 一括登録処理
            bulk_student_data = request.POST.get('bulk_student_data', '').strip()
            
            if not bulk_student_data:
                messages.error(request, '学生データを入力してください。')
                return render(request, 'school_management/student_create.html', {
                    'csrf_token': csrf_token,
                    'classroom': classroom
                })

            lines = bulk_student_data.split('\n')
            errors = []
            pending_students = []
            seen_student_numbers = {}
            seen_emails = {}

            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue

                parts = [part.strip() for part in line.split(',')]
                if len(parts) < 4:
                    errors.append(f'行{line_num}: 必要な項目が不足しています（学籍番号,氏名,ふりがな,メールアドレス） - {line}')
                    continue

                student_number = parts[0]
                full_name = parts[1]
                furigana = parts[2]
                email = parts[3] if parts[3].strip() else None

                # 正規化
                student_number = Student.clean_student_number(student_number)
                email = Student.clean_email(email)

                if not student_number or not full_name or not furigana or not email:
                    errors.append(f'行{line_num}: 学籍番号・氏名・ふりがな・メールアドレスは必須です')
                    continue

                duplicate_student_line = seen_student_numbers.get(student_number)
                if duplicate_student_line is not None:
                    errors.append(
                        f'行{line_num}: 学籍番号 "{student_number}" が入力内で重複しています（行{duplicate_student_line}）'
                    )
                    continue
                seen_student_numbers[student_number] = line_num

                if email:
                    seen_email_data = seen_emails.get(email)
                    if seen_email_data:
                        seen_student_number, seen_line_num = seen_email_data
                        if seen_student_number != student_number:
                            errors.append(
                                f'行{line_num}: メールアドレス "{email}" が入力内で学籍番号の異なる学生（行{seen_line_num}）に使われています。'
                            )
                            continue
                    seen_emails[email] = (student_number, line_num)

                pending_students.append({
                    'line_num': line_num,
                    'student_number': student_number,
                    'full_name': full_name,
                    'furigana': furigana,
                    'email': email,
                })

            if pending_students:
                # DB全体での重複・不整合チェック
                for row in pending_students:
                    sn = row['student_number']
                    em = row['email']
                    line_num = row['line_num']

                    student_by_number = Student.objects.filter(role='student', student_number=sn).first()
                    student_by_email = Student.objects.filter(role='student', email=em).first() if em else None

                    # パターンC: 不整合エラー
                    if student_by_number and student_by_email and student_by_number.id != student_by_email.id:
                        errors.append(
                            f'行{line_num}: 学籍番号 "{sn}" とメールアドレス "{em}" は、それぞれ別の既存の学生に使用されています。'
                        )
                    elif student_by_number and em and student_by_number.email != em:
                        errors.append(
                            f'行{line_num}: 学籍番号 "{sn}" は既に別のメールアドレス（例: "{student_by_number.email or "登録なし"}"）で登録されています。'
                        )
                    elif student_by_email and student_by_email.student_number != sn:
                        errors.append(
                            f'行{line_num}: メールアドレス "{em}" は既に別の学籍番号（例: "{student_by_email.student_number}"）で登録されています。'
                        )
                    else:
                        # エラーがない場合、既存の紐付け重複をチェック
                        existing_student = student_by_number or student_by_email
                        if existing_student:
                            if classroom:
                                if classroom.students.filter(id=existing_student.id).exists():
                                    errors.append(
                                        f'行{line_num}: 学生 "{existing_student.full_name}"（学籍番号: {sn}）は既にこのクラスに登録されています'
                                    )
                            else:
                                if existing_student.managed_by.filter(id=request.user.id).exists():
                                    errors.append(
                                        f'行{line_num}: 学籍番号 "{sn}" は既にあなたの管理下に登録されています'
                                    )
                            row['existing_student'] = existing_student
                        else:
                            row['existing_student'] = None

            if errors:
                for error in errors[:10]:
                    messages.error(request, error)
                if len(errors) > 10:
                    messages.error(request, f'他に{len(errors) - 10}個のエラーがあります。')
                messages.error(request, '整合性を優先するため、一括登録は全件中止しました。内容を修正して再実行してください。')
                return render(request, 'school_management/student_create.html', {
                    'csrf_token': csrf_token,
                    'classroom': classroom
                })

            try:
                with transaction.atomic():
                    created_count = 0
                    linked_count = 0
                    for row in pending_students:
                        email = row['email']
                        student_number = row['student_number']
                        full_name = row['full_name']
                        furigana = row['furigana']
                        existing_student = row.get('existing_student')
                        
                        if not existing_student:
                            default_password = f"student_{student_number}"
                            student = Student.objects.create_user(
                                email=email,
                                full_name=full_name,
                                password=default_password,
                                student_number=student_number,
                                furigana=furigana,
                                role='student'
                            )
                            created_count += 1
                        else:
                            student = existing_student
                            if not student.furigana and furigana:
                                student.furigana = furigana
                                student.save(update_fields=['furigana'])
                            linked_count += 1
                            
                        TeacherStudentAssignment.assign(request.user, student)

                        if classroom:
                            ClassRoomEnrollment.enroll(classroom, student)
                            from school_management.models import StudentClassPoints
                            StudentClassPoints.objects.get_or_create(student=student, classroom=classroom, defaults={'points': 0})
            except IntegrityError as e:
                messages.error(
                    request,
                    '同時更新により重複が発生したため、一括登録をロールバックしました。再度実行してください。'
                )
                return render(request, 'school_management/student_create.html', {
                    'csrf_token': csrf_token,
                    'classroom': classroom
                })
            except Exception as e:
                messages.error(
                    request,
                    f'一括登録中にエラーが発生したため、処理を中止してロールバックしました。: {str(e)}'
                )
                return render(request, 'school_management/student_create.html', {
                    'csrf_token': csrf_token,
                    'classroom': classroom
                })

            if classroom:
                messages.success(request, f'合計 {len(pending_students)}名 の学生をクラスに追加しました。（新規登録: {created_count}名, 既存紐づけ: {linked_count}名）')
                return redirect(f"{reverse('school_management:class_detail', args=[classroom.id])}?active_tab=students")
            else:
                messages.success(request, f'合計 {len(pending_students)}名 の学生を登録しました。（新規登録: {created_count}名, 既存紐づけ: {linked_count}名）')
                return redirect('school_management:student_list')
        
        else:
            # 単体登録処理
            student_number = request.POST.get('student_number')
            full_name = request.POST.get('full_name')
            furigana = request.POST.get('furigana')
            email = request.POST.get('email')
            memo = request.POST.get('memo', '')

            if student_number and full_name and furigana and email:
                # 正規化
                student_number = Student.clean_student_number(student_number)
                email = Student.clean_email(email)
                
                try:
                    # DBから学籍番号およびメールで検索
                    student_by_number = Student.objects.filter(role='student', student_number=student_number).first()
                    student_by_email = Student.objects.filter(role='student', email=email).first() if email else None
                    
                    # パターンC: 不整合エラー
                    if student_by_number and student_by_email and student_by_number.id != student_by_email.id:
                        messages.error(request, f'学籍番号 "{student_number}" とメールアドレス "{email}" は、それぞれ別の既存の学生に使用されています。')
                        return render(request, 'school_management/student_create.html', {
                            'csrf_token': csrf_token,
                            'classroom': classroom
                        })
                    elif student_by_number and email and student_by_number.email != email:
                        messages.error(request, f'学籍番号 "{student_number}" は既に別のメールアドレス（例: "{student_by_number.email or "登録なし"}"）で登録されています。')
                        return render(request, 'school_management/student_create.html', {
                            'csrf_token': csrf_token,
                            'classroom': classroom
                        })
                    elif student_by_email and student_by_email.student_number != student_number:
                        messages.error(request, f'メールアドレス "{email}" は既に別の学籍番号（例: "{student_by_email.student_number}"）で登録されています。')
                        return render(request, 'school_management/student_create.html', {
                            'csrf_token': csrf_token,
                            'classroom': classroom
                        })
                    
                    # 既存のアカウント重複チェック
                    existing_student = student_by_number or student_by_email
                    if existing_student:
                        if classroom:
                            if classroom.students.filter(id=existing_student.id).exists():
                                messages.error(request, f'学生 "{existing_student.full_name}"（学籍番号: {student_number}）は既にこのクラスに登録されています。')
                                return render(request, 'school_management/student_create.html', {
                                    'csrf_token': csrf_token,
                                    'classroom': classroom
                                })
                        else:
                            if existing_student.managed_by.filter(id=request.user.id).exists():
                                messages.error(request, f'学籍番号 "{student_number}" は既にあなたの管理下に登録されています。')
                                return render(request, 'school_management/student_create.html', {
                                    'csrf_token': csrf_token,
                                    'classroom': classroom
                                })
                    
                    is_new = False
                    if not existing_student:
                        # 学生新規作成
                        default_password = f"student_{student_number}"
                        student = Student.objects.create_user(
                            email=email,
                            full_name=full_name,
                            password=default_password,
                            student_number=student_number,
                            furigana=furigana,
                            memo=memo,
                            role='student'
                        )
                        is_new = True
                    else:
                        student = existing_student
                        update_fields = []
                        if not student.furigana and furigana:
                            student.furigana = furigana
                            update_fields.append('furigana')
                        if memo and not student.memo:
                            student.memo = memo
                            update_fields.append('memo')
                        if update_fields:
                            student.save(update_fields=update_fields)
                    
                    # 担当教員として紐づけ
                    TeacherStudentAssignment.assign(request.user, student)

                    # クラス登録の場合：クラスにも紐づけ、ポイント初期化
                    if classroom:
                        ClassRoomEnrollment.enroll(classroom, student)
                        from school_management.models import StudentClassPoints
                        StudentClassPoints.objects.get_or_create(student=student, classroom=classroom, defaults={'points': 0})
                    
                    if classroom:
                        if is_new:
                            messages.success(request, f'{full_name}さん（学籍番号: {student_number}）を新規作成し、クラスに追加しました。')
                        else:
                            messages.success(request, f'{full_name}さん（学籍番号: {student_number}）の既存アカウントをクラスに紐づけました。')
                        return redirect(f"{reverse('school_management:class_detail', args=[classroom.id])}?active_tab=students")
                    else:
                        if is_new:
                            messages.success(request, f'{full_name}さん（学籍番号: {student_number}）を新規追加しました。')
                        else:
                            messages.success(request, f'{full_name}さん（学籍番号: {student_number}）の既存アカウントを紐づけました。')
                        return redirect('school_management:student_list')
                        
                except IntegrityError as e:
                    error_message = str(e).lower()
                    if 'student_number' in error_message or 'unique constraint' in error_message:
                        messages.error(request, f'学籍番号 "{student_number}" は既に登録されています。別の学籍番号を入力してください。')
                    elif 'email' in error_message:
                        messages.error(request, f'メールアドレス "{email}" は既に登録されています。別のメールアドレスを入力してください。')
                    else:
                        messages.error(request, 'データの重複により登録できませんでした。入力内容を確認してください。')
                    return render(request, 'school_management/student_create.html', {
                        'csrf_token': csrf_token,
                        'classroom': classroom
                    })
                    
                except Exception as e:
                    messages.error(request, f'学生の追加中にエラーが発生しました: {str(e)}')
                    return render(request, 'school_management/student_create.html', {
                        'csrf_token': csrf_token,
                        'classroom': classroom
                    })
            else:
                messages.error(request, '必須項目を入力してください。')
    
    return render(request, 'school_management/student_create.html', {
        'csrf_token': csrf_token,
        'classroom': classroom
    })

# 学生のポイント更新
@login_required
@csrf_exempt
@require_POST
def update_student_points(request, student_id):
    """学生のポイントを更新する（クラス独立型）

    JSON ボディで { "points": <数値>, "class_id": <クラスID> } を受け取る。
    class_id は必須で、クラス単位の `StudentClassPoints` のみを更新する。
    総合ポイント（CustomUser.points）は使用しない。
    """
    if request.method == 'POST' and request.headers.get('content-type') == 'application/json':
        try:
            import json
            data = json.loads(request.body)
            points = data.get('points', 0)

            student = get_object_or_404(CustomUser, id=student_id, role='student')
            class_id = data.get('class_id')

            if not class_id:
                return JsonResponse({'success': False, 'error': 'class_idが必須です'})

            # 担当教師のチェックを追加
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
            
            scp, created = StudentClassPoints.objects.get_or_create(
                student=student,
                classroom=classroom,
                defaults={'points': 0}
            )
            StudentClassPoints.objects.filter(id=scp.id).update(
                points=int(points),
                updated_at=timezone.now(),
            )

            return JsonResponse({'success': True, 'message': 'ポイントが更新されました'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': '不正なリクエストです'})