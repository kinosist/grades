from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch
from django.db import transaction
from django.db.utils import OperationalError
from django.views.decorators.http import require_http_methods
from ...models import Student, ClassRoom

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
                    student = Student.objects.get(student_number=student_number, role='student', managed_by=request.user)
                    student_name = student.full_name
                    student.delete()
                    messages.success(request, f'{student_name}さんを削除しました。')
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
            managed_by=request.user
        ).prefetch_related('classroom_set').order_by('student_number')
        
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
        # prefetch_relatedされたデータを効率的に利用
        for student in students_page:
            student.teacher_classrooms = [
                c for c in student.classroom_set.all() if c.id in teacher_classroom_ids
            ]
    except OperationalError:
        messages.error(request, 'データベースの構造が最新ではありません。マイグレーションを実行してください。')
        students_page = []
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
        managed_by=request.user
    ).prefetch_related(
        Prefetch('classroom_set', queryset=ClassRoom.objects.all())
    ).order_by('student_number')

    try:
        if not students_to_delete.exists():
            messages.error(request, '削除対象の学生が見つかりません。')
            return redirect('school_management:student_list')

        # 各学生の関連情報を集計
        student_details = []
        for student in students_to_delete:
            classrooms = student.classroom_set.all()
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

    try:
        student_ids = [int(sid.strip()) for sid in student_ids_str.split(',') if sid.strip()]
    except ValueError:
        messages.error(request, '無効な学生IDです。')
        return redirect('school_management:student_list')

    # トランザクション内で処理を実行
    try:
        with transaction.atomic():
            # 処理対象の学生を取得
            target_students = Student.objects.filter(
                id__in=student_ids,
                role='student',
                managed_by=request.user
            )

            processed_count = target_students.count()
            processed_names = list(target_students.values_list('full_name', flat=True))

            if processed_count == 0:
                messages.error(request, '対象の学生が見つかりません。')
                return redirect('school_management:student_list')

            if delete_type == 'unlink':
                # 担当から外す処理
                # 1. managed_byから自分を外す
                for student in target_students:
                    student.managed_by.remove(request.user)
                
                # 2. 自分が担当しているすべてのクラスから学生を外す
                teacher_classrooms = request.user.classrooms.all()
                for classroom in teacher_classrooms:
                    classroom.students.remove(*target_students)
                
                action_text = '担当から外しました'
            else:
                # 完全削除処理（関連データはCASCADEで自動削除）
                target_students.delete()
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