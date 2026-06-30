from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.urls import reverse
from ...models import CustomUser

@login_required
def admin_teacher_management(request):
    """管理者用教員管理ページ"""
    if request.user.role != 'admin':
        messages.error(request, '管理者のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    # 既存の教員一覧を取得
    teachers = CustomUser.objects.filter(role='teacher').order_by('created_at')
    
    # 教員追加・削除・生徒削除処理
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_teacher':
            email = request.POST.get('email')
            full_name = request.POST.get('full_name')
            furigana = request.POST.get('furigana')
            teacher_id = request.POST.get('teacher_id')
            password = request.POST.get('password')
            
            if email and full_name and password:
                try:
                    # メールアドレスの重複チェック
                    if CustomUser.objects.filter(email=email, role__in=['teacher', 'admin']).exists():
                        messages.error(request, f'メールアドレス "{email}" は既に登録されています。')
                    else:
                        # 教員作成
                        teacher = CustomUser.objects.create_user(
                            email=email,
                            full_name=full_name,
                            password=password,
                            role='teacher',
                            teacher_id=teacher_id or '',
                            furigana=furigana or ''
                        )
                        messages.success(request, f'{full_name}さん（教員ID: {teacher_id}）を追加しました。')
                        return redirect('school_management:admin_teacher_management')
                except Exception as e:
                    messages.error(request, f'教員の追加中にエラーが発生しました: {str(e)}')
            else:
                messages.error(request, '必須項目を入力してください。')
        
        elif action == 'delete_teacher':
            teacher_id = request.POST.get('teacher_id')
            if teacher_id:
                try:
                    teacher = CustomUser.objects.get(id=teacher_id, role='teacher')
                    teacher_name = teacher.full_name
                    teacher.delete()
                    messages.success(request, f'{teacher_name}さんを削除しました。')
                    return redirect('school_management:admin_teacher_management')
                except CustomUser.DoesNotExist:
                    messages.error(request, '教員が見つかりません。')
                except Exception as e:
                    messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
        
        elif action == 'delete_student':
            student_id = request.POST.get('student_id')
            if student_id:
                try:
                    student = CustomUser.objects.get(id=student_id, role='student')
                    student_name = student.full_name
                    student_number = student.student_number
                    student.delete()
                    messages.success(request, f'生徒 {student_name}さん（学籍番号: {student_number}）を削除しました。')
                    return redirect(f"{reverse('school_management:admin_teacher_management')}?tab=students")
                except CustomUser.DoesNotExist:
                    messages.error(request, '生徒が見つかりません。')
                except Exception as e:
                    messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
        
        elif action == 'bulk_delete_students':
            select_all = request.POST.get('select_all') == 'true'
            try:
                if select_all:
                    # フィルタパラメータを取得してクエリセットを再構築
                    search_query = request.POST.get('search', '').strip()
                    teacher_filter_id = request.POST.get('teacher_id', '').strip()
                    orphan_only = request.POST.get('orphan_only', '') == 'on'
                    deselected_ids = request.POST.getlist('deselected_student_ids')
                    
                    student_qs = CustomUser.objects.filter(role='student')
                    if search_query:
                        student_qs = student_qs.filter(
                            Q(student_number__icontains=search_query) |
                            Q(full_name__icontains=search_query) |
                            Q(furigana__icontains=search_query) |
                            Q(email__icontains=search_query)
                        )
                    if teacher_filter_id:
                        student_qs = student_qs.filter(managed_by__id=teacher_filter_id)
                    if orphan_only:
                        student_qs = student_qs.filter(managed_by__isnull=True)
                        
                    if deselected_ids:
                        student_qs = student_qs.exclude(id__in=deselected_ids)
                        
                    deleted_count, _ = student_qs.delete()
                    messages.success(request, f'選択した {deleted_count}名の生徒を削除しました。')
                else:
                    student_ids = request.POST.getlist('selected_student_ids')
                    if student_ids:
                        deleted_count, _ = CustomUser.objects.filter(id__in=student_ids, role='student').delete()
                        messages.success(request, f'選択した {deleted_count}名の生徒を削除しました。')
                    else:
                        messages.error(request, '削除する生徒が選択されていません。')
                return redirect(f"{reverse('school_management:admin_teacher_management')}?tab=students")
            except Exception as e:
                messages.error(request, f'一括削除中にエラーが発生しました: {str(e)}')
    
    # クエリパラメータの取得
    active_tab = request.GET.get('tab', 'teachers')
    search_query = request.GET.get('search', '').strip()
    teacher_filter_id = request.GET.get('teacher_id', '').strip()
    orphan_only = request.GET.get('orphan_only', '') == 'on'
    
    # 既存の生徒一覧を取得（担当教員の情報を効率的にロード）
    student_qs = CustomUser.objects.filter(role='student').prefetch_related('managed_by').order_by('student_number')
    
    # フィルターが適用されているか
    has_filter = bool(search_query or teacher_filter_id or orphan_only)
    
    # フリーワード検索フィルタ
    if search_query:
        student_qs = student_qs.filter(
            Q(student_number__icontains=search_query) |
            Q(full_name__icontains=search_query) |
            Q(furigana__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    # 教員フィルタ
    if teacher_filter_id:
        student_qs = student_qs.filter(managed_by__id=teacher_filter_id)
        
    # 孤立生徒フィルタ
    if orphan_only:
        student_qs = student_qs.filter(managed_by__isnull=True)
        
    # 絞り込み後の件数（ページネーション前）
    filtered_students_count = student_qs.count()
    
    # 統計情報の取得
    total_students_count = CustomUser.objects.filter(role='student').count()
    orphan_students_count = CustomUser.objects.filter(role='student', managed_by__isnull=True).count()
    
    # ページネーション設定 (1ページ50件)
    paginator = Paginator(student_qs, 50)
    page = request.GET.get('page')
    try:
        students_page = paginator.page(page)
    except PageNotAnInteger:
        students_page = paginator.page(1)
    except EmptyPage:
        students_page = paginator.page(paginator.num_pages)
        
    context = {
        'teachers': teachers,
        'students_page': students_page,
        'active_tab': active_tab,
        'search_query': search_query,
        'teacher_filter_id': teacher_filter_id,
        'orphan_only': orphan_only,
        'has_filter': has_filter,
        'filtered_students_count': filtered_students_count,
        'total_students_count': total_students_count,
        'orphan_students_count': orphan_students_count,
    }
    return render(request, 'school_management/admin_teacher_management.html', context)
