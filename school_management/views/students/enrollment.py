import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.views.decorators.http import require_POST
from django.db import IntegrityError, transaction
from django.db.models import Q
from ...models import ClassRoom, CustomUser, Student, StudentClassPoints


@login_required
def bulk_student_add(request, class_id):
    """学生一括追加（既存学生から選択）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        selected_student_ids = request.POST.getlist('selected_students')
        if not selected_student_ids:
            messages.error(request, '追加する学生を選択してください。')
        else:
            added_count = 0
            for student_id in selected_student_ids:
                try:
                    student = CustomUser.objects.get(id=student_id, role='student')
                    if not classroom.students.filter(id=student.id).exists():
                        classroom.students.add(student)
                        # クラスポイントを0で初期化
                        StudentClassPoints.objects.get_or_create(
                            student=student,
                            classroom=classroom,
                            defaults={'points': 0}
                        )
                        added_count += 1
                except CustomUser.DoesNotExist:
                    continue
            
            if added_count > 0:
                messages.success(request, f'{added_count}人の学生をクラスに追加しました。')
                return redirect('school_management:class_detail', class_id=class_id)
            else:
                messages.warning(request, '追加された学生はいませんでした。')
    
    # 既にクラスに所属している学生を除外
    existing_student_ids = classroom.students.values_list('id', flat=True)
    available_students = CustomUser.objects.filter(
        role='student',
        student_number__isnull=False,
        student_number__gt=''
    ).exclude(id__in=existing_student_ids).order_by('student_number')
    
    # 検索機能
    search_query = request.GET.get('search', '')
    if search_query:
        available_students = available_students.filter(
            Q(student_number__icontains=search_query) |
            Q(full_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    context = {
        'classroom': classroom,
        'available_students': available_students,
        'search_query': search_query,
    }
    return render(request, 'school_management/class_student_select.html', context)


@login_required
def bulk_student_add_csv(request, class_id):
    """学生一括追加（CSV形式）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        student_data = request.POST.get('student_data', '').strip()
        
        if not student_data:
            messages.error(request, '学生データを入力してください。')
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})
        
        lines = student_data.split('\n')
        errors = []
        pending_students = []
        seen_student_numbers = {}
        seen_emails = {}
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
                
            # タブまたはカンマで分割
            parts = line.replace('\t', ',').split(',')
            if len(parts) < 2:
                errors.append(f'行{line_num}: 形式が正しくありません - {line}')
                continue
            
            student_number = parts[0].strip()
            full_name = parts[1].strip() if len(parts) > 1 else ""
            email = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
            
            #  【修正箇所】名前が空っぽ（必須エラー）の場合、スキップしてエラーにする
            if not full_name:
                errors.append(f'行{line_num}: 氏名が入力されていません - {student_number}')
                continue

            duplicate_student_line = seen_student_numbers.get(student_number)
            if duplicate_student_line is not None:
                errors.append(
                    f'行{line_num}: 学生番号 "{student_number}" が入力内で重複しています（行{duplicate_student_line}）'
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
                    errors.append(f'行{row["line_num"]}: 学生番号が既に存在します - {row["student_number"]}')
                if row['email'] and row['email'] in existing_emails:
                    errors.append(f'行{row["line_num"]}: メールアドレスが既に存在します - {row["email"]}')

        if errors:
            for error in errors[:5]:
                messages.error(request, error)
            if len(errors) > 5:
                messages.error(request, f'他に{len(errors) - 5}個のエラーがあります。')
            messages.error(request, '整合性を優先するため、一括追加は全件中止しました。内容を修正して再実行してください。')
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})

        try:
            with transaction.atomic():
                students_to_create = []
                for row in pending_students:
                    students_to_create.append(Student(
                        email=Student.objects.normalize_email(row['email']) if row['email'] else None,
                        full_name=row['full_name'],
                        password=make_password(None),
                        role='student',
                        student_number=row['student_number'],
                    ))
                created_students = Student.objects.bulk_create(students_to_create, batch_size=500)

                through_model = ClassRoom.students.through
                through_model.objects.bulk_create([
                    through_model(classroom_id=classroom.id, customuser_id=student.id)
                    for student in created_students
                ], batch_size=500)

                StudentClassPoints.objects.bulk_create([
                    StudentClassPoints(student=student, classroom=classroom, points=0)
                    for student in created_students
                ], batch_size=500)
        except IntegrityError:
            messages.error(
                request,
                '同時更新により重複が発生したため、一括追加をロールバックしました。再度実行してください。'
            )
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})
        except Exception as e:
            messages.error(request, f'一括追加中にエラーが発生したためロールバックしました: {str(e)}')
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})
        
        messages.success(request, f'{len(pending_students)}人の学生を追加しました。')
        return redirect('school_management:class_detail', class_id=class_id)
    
    context = {
        'classroom': classroom,
    }
    return render(request, 'school_management/bulk_student_add.html', context)

# クラスから学生を除籍
@login_required
@csrf_exempt
@require_POST
def remove_student_from_class(request, student_id):
    """学生をクラスから除籍する"""
    if request.method == 'POST' and request.headers.get('content-type') == 'application/json':
        try:
            import json
            data = json.loads(request.body)
            class_id = data.get('class_id')
            
            student = get_object_or_404(CustomUser, id=student_id, role='student')
            # 担当教師のチェックを追加
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
            
            # 学生をクラスから削除
            classroom.students.remove(student)
            
            return JsonResponse({'success': True, 'message': f'{student.full_name}さんをクラスから除籍しました'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': '不正なリクエストです'})