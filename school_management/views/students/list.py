from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import transaction
from django.db.utils import OperationalError
from django.views.decorators.http import require_http_methods
from ...models import Student, ClassRoomEnrollment, TeacherStudentAssignment

# 学生管理ビュー
@login_required
def student_list_view(request):
    """学生一覧（すべての学生）"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    # 削除処理
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete_student':
            student_number = request.POST.get('student_number')
            if student_number:
                try:
                    student = Student.objects.get(
                        student_number=student_number,
                        role='student',
                        teacher_assignments__teacher=request.user,
                        teacher_assignments__is_active=True,
                    )
                    student_name = student.full_name
                    TeacherStudentAssignment.unassign(request.user, student)
                    teacher_classrooms = request.user.classrooms.all()
                    ClassRoomEnrollment.bulk_unenroll(teacher_classrooms, [student])
                    messages.success(request, f'{student_name}さんを担当から外しました。')
                    return redirect('school_management:student_list')
                except Student.DoesNotExist:
                    messages.error(request, '学生が見つかりません。')
                except OperationalError:
                    messages.error(request, 'データベースの構造が最新ではありません。マイグレーションを実行してください。')
                except Exception as e:
                    messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
    
    # すべての学生を表示
    try:
        students = Student.objects.filter(
            role='student',
            student_number__gt='',
            teacher_assignments__teacher=request.user,
            teacher_assignments__is_active=True,
        ).order_by('student_number')

        # 検索機能を追加
        search_query = request.GET.get('search', '')
        if search_query:
            students = students.filter(
                Q(student_number__icontains=search_query) |
                Q(full_name__icontains=search_query)
            )

        paginator = Paginator(students, 30)
        page_number = request.GET.get('page')
        students_page = paginator.get_page(page_number)

        # ログイン教員の担当クラスIDセットを取得
        teacher_classroom_ids = set(request.user.classrooms.all().values_list('id', flat=True))

        # 各学生オブジェクトに、ログイン教員が担当するクラスのリストを追加
        # N+1対策: 学生ごとにクエリを発行せず、一括取得したマップから引く
        page_student_ids = [s.id for s in students_page]
        enrollment_map = {}
        for enrollment in ClassRoomEnrollment.objects.filter(
            student_id__in=page_student_ids,
            classroom_id__in=teacher_classroom_ids,
            is_active=True,
        ).select_related('classroom'):
            enrollment_map.setdefault(enrollment.student_id, []).append(enrollment.classroom)

        for student in students_page:
            student.teacher_classrooms = enrollment_map.get(student.id, [])
    except OperationalError:
        messages.error(request, 'データベースの構造が最新ではありません。マイグレーションを実行してください。')
        students_page = Paginator([], 30).get_page(1)
        search_query = request.GET.get('search', '')

    context = {
        'students': students_page,
        'students_page': students_page,
        'search_query': search_query,
    }
    return render(request, 'school_management/student_list.html', context)


@login_required
@require_http_methods(["POST"])
def student_bulk_delete_confirm(request):
    """一括削除確認画面"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    student_ids_str = request.POST.get('student_ids', '')
    select_all_pages = request.POST.get('select_all_pages') == 'true'
    search_query = request.POST.get('search_query', '')
    deselected_ids_str = request.POST.get('deselected_student_ids', '')

    if select_all_pages:
        try:
            students_qs = Student.objects.filter(
                role='student',
                student_number__gt='',
                teacher_assignments__teacher=request.user,
                teacher_assignments__is_active=True,
            )
            if search_query:
                students_qs = students_qs.filter(
                    Q(student_number__icontains=search_query) |
                    Q(full_name__icontains=search_query)
                )
            if deselected_ids_str:
                try:
                    deselected_ids = [int(x.strip()) for x in deselected_ids_str.split(',') if x.strip()]
                except ValueError:
                    messages.error(request, '無効な学生IDです。')
                    return redirect('school_management:student_list')
                students_qs = students_qs.exclude(id__in=deselected_ids)
            student_ids = list(students_qs.values_list('id', flat=True))
            student_ids_str = ','.join(map(str, student_ids))
        except OperationalError:
            messages.error(request, 'データベースの構造が最新ではありません。マイグレーションを実行してください。')
            return redirect('school_management:student_list')
    else:
        if not student_ids_str:
            messages.error(request, '削除対象の学生が選択されていません。')
            return redirect('school_management:student_list')

        try:
            student_ids = [int(sid.strip()) for sid in student_ids_str.split(',') if sid.strip()]
        except ValueError:
            messages.error(request, '無効な学生IDです。')
            return redirect('school_management:student_list')

    # 削除対象の学生を取得
    students_to_delete = Student.objects.filter(
        id__in=student_ids,
        role='student',
        teacher_assignments__teacher=request.user,
        teacher_assignments__is_active=True,
    ).order_by('student_number')

    try:
        if not students_to_delete.exists():
            messages.error(request, '削除対象の学生が見つかりません。')
            return redirect('school_management:student_list')

        # 各学生の関連情報を集計
        # N+1対策: 一括取得したマップから各学生のクラスを引く
        students_to_delete = list(students_to_delete)
        enrollment_map = {}
        for enrollment in ClassRoomEnrollment.objects.filter(
            student_id__in=[s.id for s in students_to_delete],
            classroom__teachers=request.user,
            is_active=True,
        ).select_related('classroom'):
            enrollment_map.setdefault(enrollment.student_id, []).append(enrollment.classroom)

        student_details = []
        for student in students_to_delete:
            classrooms = enrollment_map.get(student.id, [])
            classroom_names = [f"{c.get_semester_display()} {c.class_name} ({c.year})" for c in classrooms]

            student_details.append({
                'student': student,
                'classrooms': classroom_names,
                'classroom_count': len(classroom_names),
            })
    except OperationalError:
        messages.error(request, 'データベースの構造が最新ではありません。マイグレーションを実行してください。')
        return redirect('school_management:student_list')

    context = {
        'students_to_delete': student_details,
        'total_count': len(student_details),
        'student_ids': student_ids_str,
    }
    return render(request, 'school_management/student_bulk_delete_confirm.html', context)


@login_required
@require_http_methods(["POST"])
def student_bulk_delete_execute(request):
    """一括削除・担当解除実行"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    student_ids_str = request.POST.get('student_ids', '')
    delete_type = request.POST.get('delete_type')
    
    if not student_ids_str:
        messages.error(request, '対象の学生が選択されていません。')
        return redirect('school_management:student_list')

    if delete_type not in ['unlink', 'hard_delete']:
        messages.error(request, '無効な操作です。')
        return redirect('school_management:student_list')

    if delete_type == 'hard_delete' and request.user.role != 'admin':
        messages.error(request, '完全削除は管理者のみ実行できます。')
        return redirect('school_management:student_list')

    try:
        student_ids = [int(sid.strip()) for sid in student_ids_str.split(',') if sid.strip()]
    except ValueError:
        messages.error(request, '無効な学生IDです。')
        return redirect('school_management:student_list')

    # トランザクション内で処理を実行
    try:
        with transaction.atomic():
            # 処理対象の学生を取得
            target_students = list(Student.objects.filter(
                id__in=student_ids,
                role='student',
                teacher_assignments__teacher=request.user,
                teacher_assignments__is_active=True,
            ))

            processed_count = len(target_students)
            processed_names = [s.full_name for s in target_students]

            if processed_count == 0:
                messages.error(request, '対象の学生が見つかりません。')
                return redirect('school_management:student_list')

            if delete_type == 'unlink':
                # 担当から外す処理（履歴として保持し、物理削除はしない）
                # 1. 担当から自分を外す
                TeacherStudentAssignment.bulk_unassign(request.user, target_students)

                # 2. 自分が担当しているすべてのクラスから学生を外す
                teacher_classrooms = request.user.classrooms.all()
                ClassRoomEnrollment.bulk_unenroll(teacher_classrooms, target_students)

                action_text = '担当から外しました'
            else:
                # 完全削除処理（関連データはCASCADEで自動削除）
                Student.objects.filter(id__in=[s.id for s in target_students]).delete()
                action_text = 'システムから完全に削除しました'

            # 成功メッセージ
            message = f'{processed_count}人の学生を{action_text}: {", ".join(processed_names[:5])}'
            if processed_count > 5:
                message += f' ほか {processed_count - 5} 人'
            messages.success(request, message)

    except OperationalError:
        messages.error(request, 'データベースの構造が最新ではありません。マイグレーションを実行してください。')
    except Exception as e:
        messages.error(request, f'処理中にエラーが発生しました: {str(e)}')

    return redirect('school_management:student_list')