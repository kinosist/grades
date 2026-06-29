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
from ...models import CustomUser, Student, ClassRoom, StudentClassPoints

@login_required
def student_edit_view(request, student_number):
    """学生編集"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    student = get_object_or_404(CustomUser, student_number=student_number, role='student')

    csrf_token = get_token(request)
    
    if request.method == 'POST':
        # フォームデータの取得
        full_name = request.POST.get('full_name')
        furigana = request.POST.get('furigana')
        email = request.POST.get('email')
        # points = request.POST.get('points')
        
        # バリデーション
        if not full_name or not furigana:
            messages.error(request, '氏名とふりがなは必須項目です。')
        else:
            try:
                # 学生情報を更新
                student.full_name = full_name
                student.furigana = furigana
                student.email = email or ''
                
                # ポイントはクラス単位で管理するため、ここでは更新しない
                # クラス詳細画面から各クラスのポイントを個別に更新する
                
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
                if len(parts) < 3:
                    errors.append(f'行{line_num}: 必要な項目が不足しています（学籍番号,氏名,ふりがな） - {line}')
                    continue

                student_number = parts[0]
                full_name = parts[1]
                furigana = parts[2]
                email = parts[3] if len(parts) > 3 and parts[3].strip() else None
                normalized_email = Student.objects.normalize_email(email) if email else None

                if not student_number or not full_name or not furigana:
                    errors.append(f'行{line_num}: 学籍番号・氏名・ふりがなは必須です')
                    continue

                duplicate_student_line = seen_student_numbers.get(student_number)
                if duplicate_student_line is not None:
                    errors.append(
                        f'行{line_num}: 学籍番号 "{student_number}" が入力内で重複しています（行{duplicate_student_line}）'
                    )
                    continue
                seen_student_numbers[student_number] = line_num

                if normalized_email:
                    seen_email_data = seen_emails.get(normalized_email)
                    if seen_email_data:
                        seen_student_number, seen_line_num = seen_email_data
                        if seen_student_number != student_number:
                            errors.append(
                                f'行{line_num}: メールアドレス "{normalized_email}" が入力内で学籍番号の異なる学生（行{seen_line_num}）に使われています。'
                            )
                            continue
                    seen_emails[normalized_email] = (student_number, line_num)

                pending_students.append({
                    'line_num': line_num,
                    'student_number': student_number,
                    'full_name': full_name,
                    'furigana': furigana,
                    'email': normalized_email,
                })

            if pending_students:
                student_numbers = [row['student_number'] for row in pending_students]
                emails = [row['email'] for row in pending_students if row['email']]

                # メールアドレスの重複と学籍番号の不一致をチェック
                from collections import defaultdict
                existing_email_to_numbers = defaultdict(list)
                for s in Student.objects.filter(role='student', email__in=emails):
                    existing_email_to_numbers[s.email].append(s.student_number)

                if classroom:
                    # クラス登録の場合：既にクラスに所属している学生のチェック
                    existing_classroom_student_numbers = set(
                        classroom.students.filter(student_number__in=student_numbers).values_list('student_number', flat=True)
                    )
                else:
                    existing_classroom_student_numbers = set()
                    # 通常登録の場合：既にこの教員の管理下にあるかチェック
                    existing_student_numbers = set(
                        Student.objects.filter(
                            role='student',
                            student_number__in=student_numbers,
                            managed_by=request.user,
                        ).values_list('student_number', flat=True)
                    )

                for row in pending_students:
                    if classroom:
                        if row['student_number'] in existing_classroom_student_numbers:
                            errors.append(
                                f'行{row["line_num"]}: 学籍番号 "{row["student_number"]}" は既にこのクラスに登録されています'
                            )
                    else:
                        if row['student_number'] in existing_student_numbers:
                            errors.append(
                                f'行{row["line_num"]}: 学籍番号 "{row["student_number"]}" は既に登録されています'
                            )
                    
                    email = row['email']
                    student_number = row['student_number']
                    # メールが既存で、かつ入力された学籍番号と紐づいていない場合はエラー
                    if email and email in existing_email_to_numbers and student_number not in existing_email_to_numbers[email]:
                        errors.append(
                            f'行{row["line_num"]}: メールアドレス "{email}" は別の学籍番号（例: "{existing_email_to_numbers[email][0]}"）のアカウントで既に使用されています。'
                        )

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
                        
                        student = None
                        if email:
                            student = Student.objects.filter(
                                email=email, student_number=student_number, role='student'
                            ).first()
                        else:
                            student = Student.objects.filter(
                                student_number=student_number, role='student'
                            ).first()
                        
                        is_new = False
                        if not student:
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
                            is_new = True
                        else:
                            # 既存学生でかつふりがながない場合は更新
                            if not student.furigana and furigana:
                                student.furigana = furigana
                                student.save(update_fields=['furigana'])
                            linked_count += 1
                            
                        # ManyToMany のため、add で担当教員として紐づける
                        student.managed_by.add(request.user)

                        # クラス登録の場合は、クラスにも紐づけてポイントレコードを作成
                        if classroom:
                            classroom.students.add(student)
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
            
            if student_number and full_name and furigana:
                # メールアドレスを空文字列の場合はNoneに変換
                email = email.strip() if email and email.strip() else None
                
                try:
                    # 重複チェックの分岐
                    if classroom:
                        # クラス登録の場合：既にそのクラスに登録されているかチェック
                        if classroom.students.filter(student_number=student_number).exists():
                            messages.error(request, f'学籍番号 "{student_number}" の学生は既にこのクラスに登録されています。')
                            return render(request, 'school_management/student_create.html', {
                                'csrf_token': csrf_token,
                                'classroom': classroom
                            })
                    else:
                        # 通常登録の場合：ログイン教員の管理下に既に登録されているかチェック
                        if Student.objects.filter(student_number=student_number, managed_by=request.user).exists():
                            messages.error(request, f'学籍番号 "{student_number}" は既にあなたの管理下に登録されています。')
                            return render(request, 'school_management/student_create.html', {
                                'csrf_token': csrf_token,
                                'classroom': classroom
                            })
                    
                    student = None
                    if email:
                        # メールが一致する学生を検索
                        same_email_qs = Student.objects.filter(email=email, role='student')
                        # 学籍番号も一致する学生を探す (これが本来紐づくべき学生)
                        student = same_email_qs.filter(student_number=student_number).first()

                        # もし見つからず、かつ同じメールで学籍番号が異なる学生が存在する場合
                        if student is None and same_email_qs.exclude(student_number=student_number).exists():
                            # エラーとして処理
                            existing_sn = same_email_qs.exclude(student_number=student_number).values_list('student_number', flat=True).first()
                            messages.error(request, f'メールアドレス "{email}" は学籍番号 "{existing_sn}" のアカウントで既に使用されています。')
                            return render(request, 'school_management/student_create.html', {
                                'csrf_token': csrf_token,
                                'classroom': classroom
                            })
                    else:
                        # メールがない場合、学籍番号だけで既存学生を探す
                        student = Student.objects.filter(student_number=student_number, role='student').first()
                    
                    is_new = False
                    if not student:
                        # 学生新規作成
                        default_password = f"student_{student_number}"
                        student = Student.objects.create_user(
                            email=email,
                            full_name=full_name,
                            password=default_password,
                            student_number=student_number,
                            furigana=furigana,
                            role='student'
                        )
                        is_new = True
                    else:
                        # 既存の学生で、ふりがながなければ補完
                        if not student.furigana and furigana:
                            student.furigana = furigana
                            student.save(update_fields=['furigana'])
                    
                    # 担当教員として紐づけ
                    student.managed_by.add(request.user)

                    # クラス登録の場合：クラスにも紐づけ、ポイント初期化
                    if classroom:
                        classroom.students.add(student)
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