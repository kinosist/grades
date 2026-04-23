import json
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse  
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.middleware.csrf import get_token
from django.db import IntegrityError, transaction
from django.utils import timezone
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
    
    if request.method == 'POST':
        registration_type = request.POST.get('registration_type', 'single')
        
        if registration_type == 'bulk':
            # 一括登録処理
            bulk_student_data = request.POST.get('bulk_student_data', '').strip()
            
            if not bulk_student_data:
                messages.error(request, '学生データを入力してください。')
                return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
            
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

                if email:
                    duplicate_email_line = seen_emails.get(email)
                    if duplicate_email_line is not None:
                        errors.append(
                            f'行{line_num}: メールアドレス "{email}" が入力内で重複しています（行{duplicate_email_line}）'
                        )
                        continue
                    seen_emails[email] = line_num

                pending_students.append({
                    'line_num': line_num,
                    'student_number': student_number,
                    'full_name': full_name,
                    'furigana': furigana,
                    'email': email,
                })

            if pending_students:
                student_numbers = [row['student_number'] for row in pending_students]
                emails = [row['email'] for row in pending_students if row['email']]

                existing_student_numbers = set(
                    Student.objects.filter(
                        role='student',
                        student_number__in=student_numbers,
                    ).values_list('student_number', flat=True)
                )
                existing_emails = set(
                    Student.objects.filter(email__in=emails).values_list('email', flat=True)
                ) if emails else set()

                for row in pending_students:
                    if row['student_number'] in existing_student_numbers:
                        errors.append(
                            f'行{row["line_num"]}: 学籍番号 "{row["student_number"]}" は既に登録されています'
                        )
                    if row['email'] and row['email'] in existing_emails:
                        errors.append(
                            f'行{row["line_num"]}: メールアドレス "{row["email"]}" は既に登録されています'
                        )

            if errors:
                for error in errors[:10]:
                    messages.error(request, error)
                if len(errors) > 10:
                    messages.error(request, f'他に{len(errors) - 10}個のエラーがあります。')
                messages.error(request, '整合性を優先するため、一括登録は全件中止しました。内容を修正して再実行してください。')
                return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})

            try:
                with transaction.atomic():
                    students_to_create = []
                    for row in pending_students:
                        students_to_create.append(Student(
                            email=Student.objects.normalize_email(row['email']) if row['email'] else None,
                            full_name=row['full_name'],
                            password='',
                            student_number=row['student_number'],
                            furigana=row['furigana'],
                            role='student',
                        ))
                    # bulk_createではset_passwordが使えないため、事前にハッシュ済みパスワードを設定する
                    for student in students_to_create:
                        student.set_password(settings.DEFAULT_STUDENT_PASSWORD)
                    Student.objects.bulk_create(students_to_create, batch_size=500)
            except IntegrityError:
                messages.error(
                    request,
                    '同時更新により重複が発生したため、一括登録をロールバックしました。再度実行してください。'
                )
                return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
            except Exception:
                messages.error(
                    request,
                    '一括登録中にエラーが発生したため、処理を中止してロールバックしました。入力内容を確認して再実行してください。'
                )
                return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})

            messages.success(request, f'{len(pending_students)}名の学生を一括登録しました。')
            return redirect('school_management:student_list')
        
        else:
            # 単体登録処理（既存の処理）
            student_number = request.POST.get('student_number')
            full_name = request.POST.get('full_name')
            furigana = request.POST.get('furigana')
            email = request.POST.get('email')
            
            if student_number and full_name and furigana:
                # メールアドレスを空文字列の場合はNoneに変換
                email = email.strip() if email and email.strip() else None
                
                try:
                    # 学籍番号の重複チェック
                    if Student.objects.filter(student_number=student_number).exists():
                        messages.error(request, f'学籍番号 "{student_number}" は既に登録されています。別の学籍番号を入力してください。')
                        return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
                    
                    # メールアドレスの重複チェック（null値は除外）
                    if email and Student.objects.filter(email=email).exists():
                        messages.error(request, f'メールアドレス "{email}" は既に登録されています。別のメールアドレスを入力してください。')
                        return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
                    
                    # 学生作成
                    # デフォルトパスワードを生成（学籍番号をベースに）
                    default_password = f"student_{student_number}"
                    
                    Student.objects.create_user(
                        email=email,
                        full_name=full_name,
                        password=default_password,
                        student_number=student_number,
                        furigana=furigana,
                        role='student'
                    )
                    messages.success(request, f'{full_name}さん（学籍番号: {student_number}）を追加しました。')
                    return redirect('school_management:student_list')
                    
                except IntegrityError as e:
                    # データベース制約違反の場合
                    error_message = str(e).lower()
                    if 'student_number' in error_message or 'unique constraint' in error_message:
                        messages.error(request, f'学籍番号 "{student_number}" は既に登録されています。別の学籍番号を入力してください。')
                    elif 'email' in error_message:
                        messages.error(request, f'メールアドレス "{email}" は既に登録されています。別のメールアドレスを入力してください。')
                    else:
                        messages.error(request, 'データの重複により登録できませんでした。入力内容を確認してください。')
                    return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
                    
                except Exception as e:
                    messages.error(request, f'学生の追加中にエラーが発生しました: {str(e)}')
                    return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
            else:
                messages.error(request, '必須項目を入力してください。')
    
    return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})

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