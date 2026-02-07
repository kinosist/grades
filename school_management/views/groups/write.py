from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Max
from ...models import LessonSession, Group, GroupMember, CustomUser

@login_required
def group_management(request, session_id):
    """グループマスタ編集"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    students = lesson_session.classroom.students.all()
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student').order_by('group_number')
    
    # 最大グループ番号を計算
    max_group_number = 0
    if groups.exists():
        max_group_number = groups.aggregate(Max('group_number'))['group_number__max'] or 0
    
    if request.method == 'POST':
        # 既存のグループを削除
        Group.objects.filter(lesson_session=lesson_session).delete()
        
        # グループ数を取得
        group_count = int(request.POST.get('group_count', 0))
        
        for group_num in range(1, group_count + 1):
            # グループ名を取得
            group_name = request.POST.get(f'group_{group_num}_name', '').strip()
            
            group = Group.objects.create(
                lesson_session=lesson_session,
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
                        GroupMember.objects.create(
                            group=group,
                            student=student,
                            role=role
                        )
                    except CustomUser.DoesNotExist:
                        messages.warning(request, f'学籍番号 {student_id} の学生が見つかりません。')
        
        messages.success(request, 'グループ編成を保存しました。')
        return redirect('school_management:group_list', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
        'students': students,
        'groups': groups,
        'max_group_number': max_group_number,
    }
    return render(request, 'school_management/group_management.html', context)

@login_required
def group_edit_view(request, session_id, group_id):
    """グループ編集"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    group = get_object_or_404(Group, id=group_id, lesson_session=lesson_session)
    members = group.groupmember_set.all().select_related('student')
    available_students = lesson_session.classroom.students.exclude(
        id__in=members.values_list('student_id', flat=True)
    )
    
    if request.method == 'POST':
        # グループ名の更新（メンバー関連の操作以外の場合のみ）
        if 'action' not in request.POST:
            # グループ名保存フォームの場合
            group_name = request.POST.get('group_name', '').strip()
            if group_name:
                group.group_name = group_name
            else:
                # 空の場合はデフォルト名に戻す
                group.group_name = f'グループ{group.group_number}'
            group.save()
            messages.success(request, 'グループ名を保存しました。')
        
        # メンバーの更新
        if 'action' in request.POST:
            action = request.POST.get('action')
            
            # メンバー関連の操作の場合はグループ名を更新しない
            if action == 'add_member':
                student_id = request.POST.get('student_id')
                role = request.POST.get('role', '')
                if student_id:
                    try:
                        student = CustomUser.objects.get(id=student_id, role='student')
                        GroupMember.objects.create(
                            group=group,
                            student=student,
                            role=role
                        )
                        messages.success(request, f'{student.full_name}さんをグループに追加しました。')
                    except CustomUser.DoesNotExist:
                        messages.error(request, '学生が見つかりません。')
            
            elif action == 'add_members':
                # 複数のメンバーを一括追加
                selected_student_ids = request.POST.getlist('selected_students')
                default_role = request.POST.get('default_role', '')
                if selected_student_ids:
                    added_count = 0
                    for student_id in selected_student_ids:
                        try:
                            student = CustomUser.objects.get(id=student_id, role='student')
                            # 既にメンバーに含まれていないかチェック
                            if not GroupMember.objects.filter(group=group, student=student).exists():
                                GroupMember.objects.create(
                                    group=group,
                                    student=student,
                                    role=default_role
                                )
                                added_count += 1
                        except CustomUser.DoesNotExist:
                            continue
                    
                    if added_count > 0:
                        messages.success(request, f'{added_count}名の学生をグループに追加しました。')
                    else:
                        messages.warning(request, '追加された学生はいませんでした。')
                else:
                    messages.warning(request, '追加する学生を選択してください。')
            
            elif action == 'remove_member':
                member_id = request.POST.get('member_id')
                if member_id:
                    try:
                        member = GroupMember.objects.get(id=member_id, group=group)
                        student_name = member.student.full_name
                        member.delete()
                        messages.success(request, f'{student_name}さんをグループから削除しました。')
                    except GroupMember.DoesNotExist:
                        messages.error(request, 'メンバーが見つかりません。')
            
            elif action == 'update_role':
                member_id = request.POST.get('member_id')
                new_role = request.POST.get('new_role', '')
                if member_id:
                    try:
                        member = GroupMember.objects.get(id=member_id, group=group)
                        member.role = new_role
                        member.save()
                        messages.success(request, '役割を更新しました。')
                    except GroupMember.DoesNotExist:
                        messages.error(request, 'メンバーが見つかりません。')
        
        return redirect('school_management:group_edit', session_id=session_id, group_id=group_id)
    
    context = {
        'lesson_session': lesson_session,
        'group': group,
        'members': members,
        'available_students': available_students,
    }
    return render(request, 'school_management/group_edit.html', context)

@login_required
def group_add_view(request, session_id):
    """グループを追加（既存のグループを保持したまま）"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        # 既存のグループ番号の最大値を取得
        existing_groups = Group.objects.filter(lesson_session=lesson_session)
        if existing_groups.exists():
            max_group_number = existing_groups.aggregate(Max('group_number'))['group_number__max']
            new_group_number = max_group_number + 1
        else:
            new_group_number = 1
        
        # グループ名を取得
        group_name = request.POST.get('group_name', '').strip()
        
        # 新しいグループを作成
        new_group = Group.objects.create(
            lesson_session=lesson_session,
            group_number=new_group_number,
            group_name=group_name if group_name else f'グループ{new_group_number}'
        )
        
        messages.success(request, f'グループ「{new_group.display_name}」を追加しました。')
        return redirect('school_management:group_list', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
    }
    return render(request, 'school_management/group_add.html', context)

@login_required
def group_delete_view(request, session_id, group_id):
    """グループ削除"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    group = get_object_or_404(Group, id=group_id, lesson_session=lesson_session)
    
    if request.method == 'POST':
        group_name = group.display_name
        group.delete()
        messages.success(request, f'グループ「{group_name}」を削除しました。')
        return redirect('school_management:group_list', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
        'group': group,
    }
    return render(request, 'school_management/group_delete.html', context)