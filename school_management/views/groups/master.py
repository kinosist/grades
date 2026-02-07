from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Max
from ...models import ClassRoom, LessonSession, GroupMaster, GroupMasterMember, Group, GroupMember, CustomUser

@login_required
def group_master_list_view(request, class_id):
    """グループマスタ一覧"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    group_masters = GroupMaster.objects.filter(classroom=classroom).prefetch_related('members__student').order_by('group_number')
    
    # グループ統計情報を計算
    group_stats = []
    for group_master in group_masters:
        member_count = group_master.members.count()
        group_stats.append({
            'group_master': group_master,
            'member_count': member_count,
            'members': group_master.members.all()
        })
    
    # 実際にグループマスタに所属しているユニークな学生数を計算
    assigned_student_ids = GroupMasterMember.objects.filter(
        group_master__classroom=classroom
    ).values_list('student_id', flat=True).distinct()
    assigned_students_count = len(assigned_student_ids)
    
    # 総学生数と未配置学生数を計算
    total_students = classroom.students.count()
    unassigned_students = total_students - assigned_students_count
    
    context = {
        'classroom': classroom,
        'group_stats': group_stats,
        'total_students': total_students,
        'assigned_students': assigned_students_count,
        'unassigned_students': unassigned_students,
    }
    return render(request, 'school_management/group_master_list.html', context)

@login_required
def group_master_management(request, class_id):
    """グループマスタ編集（グループ編成と同様のUI）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all()
    group_masters = GroupMaster.objects.filter(classroom=classroom).prefetch_related('members__student').order_by('group_number')
    
    # 最大グループ番号を計算
    max_group_number = 0
    if group_masters.exists():
        max_group_number = group_masters.aggregate(Max('group_number'))['group_number__max'] or 0
    
    if request.method == 'POST':
        # 既存のグループマスタを削除
        GroupMaster.objects.filter(classroom=classroom).delete()
        
        # グループ数を取得
        group_count = int(request.POST.get('group_count', 0))
        
        for group_num in range(1, group_count + 1):
            # グループ名を取得
            group_name = request.POST.get(f'group_{group_num}_name', '').strip()
            
            group_master = GroupMaster.objects.create(
                classroom=classroom,
                group_number=group_num,
                group_name=group_name if group_name else f'グループ{group_num}'
            )
            
            # グループメンバーを追加
            member_keys = [key for key in request.POST.keys() if key.startswith(f'group_{group_num}_member_')]
            
            for key in member_keys:
                student_id = request.POST.get(key)
                if student_id:
                    try:
                        student = CustomUser.objects.get(student_number=student_id, role='student')
                        role = request.POST.get(f'group_{group_num}_role_{key.split("_")[-1]}', '')
                        GroupMasterMember.objects.create(
                            group_master=group_master,
                            student=student,
                            role=role
                        )
                    except CustomUser.DoesNotExist:
                        messages.warning(request, f'学籍番号 {student_id} の学生が見つかりません。')
        
        messages.success(request, 'グループマスタを保存しました。')
        return redirect('school_management:group_master_list', class_id=class_id)
    
    context = {
        'classroom': classroom,
        'students': students,
        'group_masters': group_masters,
        'max_group_number': max_group_number,
    }
    return render(request, 'school_management/group_master_management.html', context)

@login_required
def group_master_copy_to_session(request, session_id):
    """グループマスタを授業回のグループにコピー"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    classroom = lesson_session.classroom
    group_masters = GroupMaster.objects.filter(classroom=classroom).prefetch_related('members__student')
    
    if not group_masters.exists():
        messages.error(request, 'グループマスタが設定されていません。先にグループマスタを作成してください。')
        return redirect('school_management:group_list', session_id=session_id)
    
    if request.method == 'POST':
        # 既存のグループを削除（オプション）
        if request.POST.get('replace_existing') == 'on':
            Group.objects.filter(lesson_session=lesson_session).delete()
        
        # 既存のグループを取得
        existing_groups = Group.objects.filter(lesson_session=lesson_session)
        existing_groups_dict = {g.group_number: g for g in existing_groups}
        
        # グループマスタからグループをコピー
        copied_count = 0
        updated_count = 0
        for group_master in group_masters:
            # 既存のグループがあるかチェック
            if group_master.group_number in existing_groups_dict:
                # 既存のグループを更新（メンバーを追加）
                group = existing_groups_dict[group_master.group_number]
                # グループ名を更新（マスタの名前で上書き）
                if group_master.group_name:
                    group.group_name = group_master.group_name
                    group.save()
                
                # メンバーを追加（既存のメンバーは保持）
                for master_member in group_master.members.all():
                    # 既にメンバーに含まれていない場合のみ追加
                    if not GroupMember.objects.filter(group=group, student=master_member.student).exists():
                        GroupMember.objects.create(
                            group=group,
                            student=master_member.student,
                            role=master_member.role
                        )
                updated_count += 1
            else:
                # 新しいグループを作成
                group = Group.objects.create(
                    lesson_session=lesson_session,
                    group_number=group_master.group_number,
                    group_name=group_master.group_name
                )
                
                # メンバーをコピー
                for master_member in group_master.members.all():
                    GroupMember.objects.create(
                        group=group,
                        student=master_member.student,
                        role=master_member.role
                    )
                copied_count += 1
        
        if updated_count > 0 and copied_count > 0:
            messages.success(request, f'{copied_count}個のグループを新規作成し、{updated_count}個のグループを更新しました。')
        elif updated_count > 0:
            messages.success(request, f'{updated_count}個のグループを更新しました。')
        else:
            messages.success(request, f'{copied_count}個のグループをコピーしました。')
        return redirect('school_management:group_list', session_id=session_id)
    
    # 既存のグループがあるかチェック
    existing_groups = Group.objects.filter(lesson_session=lesson_session)
    has_existing_groups = existing_groups.exists()
    
    context = {
        'lesson_session': lesson_session,
        'classroom': classroom,
        'group_masters': group_masters,
        'has_existing_groups': has_existing_groups,
        'existing_group_count': existing_groups.count(),
    }
    return render(request, 'school_management/group_master_copy.html', context)