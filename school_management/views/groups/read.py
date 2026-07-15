from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from ...models import LessonSession, Group, GroupMember

@login_required
def group_list_view(request, session_id):
    """グループ一覧表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    classroom = lesson_session.classroom
    active_student_ids = set(classroom.students.values_list('id', flat=True))
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related(
        # N+1対策: メンバーと関連学生を一括取得（学籍番号順）
        Prefetch('groupmember_set', queryset=GroupMember.objects.select_related('student').order_by('student__student_number'))
    ).order_by('group_number')

    # グループ統計情報を計算（prefetch_relatedされたデータを使用）
    # 担当から外れた学生は非表示にする（データ自体は保持し、再度担当になれば表示が戻る）
    group_stats = []
    for group in groups:
        members = [m for m in group.groupmember_set.all() if m.student_id in active_student_ids]
        group_stats.append({
            'group': group,
            'member_count': len(members),  # countではなくlenを使用（DBクエリ回避）
            'members': members
        })
    
    # 実際にグループに所属しているユニークな学生数を計算（担当から外れた学生は除く）
    assigned_student_ids = GroupMember.objects.filter(
        group__lesson_session=lesson_session,
        student_id__in=active_student_ids,
    ).values_list('student_id', flat=True).distinct()
    assigned_students_count = len(assigned_student_ids)

    # 総学生数と未配置学生数を計算
    total_students = len(active_student_ids)
    unassigned_students = total_students - assigned_students_count
    
    context = {
        'lesson_session': lesson_session,
        'group_stats': group_stats,
        'total_students': total_students,
        'assigned_students': assigned_students_count,
        'unassigned_students': unassigned_students,
    }
    return render(request, 'school_management/group_list.html', context)

@login_required
def group_detail_view(request, session_id, group_id):
    """グループ詳細表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    group = get_object_or_404(Group, id=group_id, lesson_session=lesson_session)
    # 担当から外れた学生は非表示にする（データ自体は保持し、再度担当になれば表示が戻る）
    members = group.groupmember_set.filter(
        student__in=lesson_session.classroom.students
    ).select_related('student').order_by('student__student_number')
    
    context = {
        'lesson_session': lesson_session,
        'group': group,
        'members': members,
    }
    return render(request, 'school_management/group_detail.html', context)