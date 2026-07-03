import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import IntegrityError, transaction
from django.db.models import Q, Count
from django.urls import reverse
from django.utils import timezone
from ...models import ClassRoom, CustomUser, Student, StudentClassPoints, ClassRoomEnrollment, TeacherStudentAssignment


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
                        ClassRoomEnrollment.enroll(classroom, student)
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
                return redirect(f"{reverse('school_management:class_detail', args=[class_id])}?active_tab=students")
            else:
                messages.warning(request, '追加された学生はいませんでした。')
    
    # 既にクラスに所属している学生を除外
    existing_student_ids = classroom.students.values_list('id', flat=True)
    available_students = CustomUser.objects.filter(
        role='student',
        student_number__isnull=False,
        student_number__gt='',
        teacher_assignments__teacher=request.user,
        teacher_assignments__is_active=True,
    ).exclude(id__in=existing_student_ids).order_by('student_number')

    # 検索機能
    search_query = request.GET.get('search', '')
    if search_query:
        available_students = available_students.filter(
            Q(student_number__icontains=search_query) |
            Q(full_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    # ログイン教員の担当クラスIDセットを取得
    teacher_classroom_ids = set(request.user.classrooms.all().values_list('id', flat=True))

    # 各学生オブジェクトに、ログイン教員が担当するクラスのリストを追加
    # N+1対策: 学生ごとにクエリを発行せず、一括取得したマップから引く
    available_students = list(available_students)
    enrollment_map = {}
    for enrollment in ClassRoomEnrollment.objects.filter(
        student_id__in=[s.id for s in available_students],
        classroom_id__in=teacher_classroom_ids,
        is_active=True,
    ).select_related('classroom'):
        enrollment_map.setdefault(enrollment.student_id, []).append(enrollment.classroom)

    for student in available_students:
        student.teacher_classrooms = enrollment_map.get(student.id, [])

    # 他のクラスから学生をコピーするためのクラスリストを取得
    other_classes = ClassRoom.objects.filter(
        teachers=request.user
    ).exclude(id=class_id).annotate(
        student_count=Count('enrollments', filter=Q(enrollments__is_active=True))
    ).filter(
        student_count__gt=0
    ).order_by('-year', 'semester')

    other_classes_with_student_ids = []
    for oc in other_classes:
        student_ids = list(oc.students.values_list('id', flat=True))
        other_classes_with_student_ids.append({
            'class': oc,
            'student_ids_json': json.dumps(student_ids)
        })

    context = {
        'classroom': classroom,
        'available_students': available_students,
        'search_query': search_query,
        'other_classes_with_student_ids': other_classes_with_student_ids,
    }
    return render(request, 'school_management/class_student_select.html', context)


@login_required
@require_POST
def copy_students_from_class(request, class_id, source_class_id):
    """ 指定されたクラスから現在のクラスへ学生をコピーする """
    target_class = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    source_class = get_object_or_404(ClassRoom, id=source_class_id, teachers=request.user)

    if target_class.id == source_class.id:
        messages.error(request, '同じクラスからはコピーできません。')
        return redirect(f"{reverse('school_management:class_detail', args=[class_id])}?active_tab=students")

    source_students = source_class.students.all()
    target_student_ids = set(target_class.students.values_list('id', flat=True))
    
    students_to_add = [
        student for student in source_students if student.id not in target_student_ids
    ]
    
    added_count = len(students_to_add)

    if students_to_add:
        # transaction.atomic() でまとめて実行
        try:
            with transaction.atomic():
                ClassRoomEnrollment.bulk_enroll(target_class, students_to_add)

                # bulk_create StudentClassPoints
                StudentClassPoints.objects.bulk_create([
                    StudentClassPoints(student=student, classroom=target_class, points=0)
                    for student in students_to_add
                ], ignore_conflicts=True)
        except Exception as e:
            messages.error(request, f'学生のコピー中にエラーが発生しました: {e}')
            return redirect(f"{reverse('school_management:class_detail', args=[class_id])}?active_tab=students")

    if added_count > 0:
        messages.success(request, f'「{source_class.class_name}」から{added_count}人の学生をコピーしました。')
    else:
        messages.info(request, '追加する新しい学生はいませんでした（全員既に所属しています）。')

    return redirect(f"{reverse('school_management:class_detail', args=[class_id])}?active_tab=students")


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
            
            student_number = CustomUser.clean_student_number(parts[0])
            full_name = parts[1].strip() if len(parts) > 1 else ""
            email = CustomUser.clean_email(parts[2]) if len(parts) > 2 else None

            if not student_number:
                errors.append(f'行{line_num}: 学生番号が入力されていません')
                continue
            
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
                    # エラーがない場合、既存アカウントの重複チェック
                    existing_student = student_by_number or student_by_email
                    if existing_student:
                        if classroom.students.filter(id=existing_student.id).exists():
                            errors.append(
                                f'行{line_num}: 学生 "{existing_student.full_name}"（学籍番号: {sn}）は既にこのクラスに登録されています'
                            )
                        row['existing_student'] = existing_student
                    else:
                        row['existing_student'] = None

        if errors:
            for error in errors[:5]:
                messages.error(request, error)
            if len(errors) > 5:
                messages.error(request, f'他に{len(errors) - 5}個のエラーがあります。')
            messages.error(request, '整合性を優先するため、一括追加は全件中止しました。内容を修正して再実行してください。')
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})

        try:
            with transaction.atomic():
                processed_students_map = {}
                for row in pending_students:
                    email = row['email']
                    student_number = row['student_number']
                    full_name = row['full_name']
                    existing_student = row.get('existing_student')

                    is_new = False
                    if not existing_student:
                        default_password = f"student_{student_number}"
                        student = Student.objects.create_user(
                            email=email,
                            full_name=full_name,
                            password=default_password,
                            role='student',
                            student_number=student_number
                        )
                        is_new = True
                    else:
                        student = existing_student

                    if student.id not in processed_students_map:
                        TeacherStudentAssignment.assign(request.user, student)
                        processed_students_map[student.id] = {'student': student, 'is_new': is_new}

                created_students = [data['student'] for data in processed_students_map.values()]
                created_count = sum(1 for data in processed_students_map.values() if data['is_new'])
                linked_count = len(created_students) - created_count

                ClassRoomEnrollment.bulk_enroll(classroom, created_students)

                StudentClassPoints.objects.bulk_create([
                    StudentClassPoints(student=student, classroom=classroom, points=0)
                    for student in created_students
                ], batch_size=500, ignore_conflicts=True)
        except IntegrityError:
            messages.error(
                request,
                '同時更新により重複が発生したため、一括追加をロールバックしました。再度実行してください。'
            )
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})
        except Exception:
            messages.error(request, '一括追加中にエラーが発生したため、処理を中止してロールバックしました。')
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})
        
        messages.success(request, f'合計 {len(created_students)}名の学生をクラスに追加しました。（新規作成: {created_count}名, 既存共有: {linked_count}名）')
        return redirect(f"{reverse('school_management:class_detail', args=[class_id])}?active_tab=students")
    
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
            ClassRoomEnrollment.unenroll(classroom, student)
            
            return JsonResponse({'success': True, 'message': f'{student.full_name}さんをクラスから除籍しました'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': '不正なリクエストです'})