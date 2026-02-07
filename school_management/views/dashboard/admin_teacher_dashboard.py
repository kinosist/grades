from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import CustomUser

@login_required
def admin_teacher_management(request):
    """管理者用教員管理ページ"""
    if request.user.role != 'admin':
        messages.error(request, '管理者のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    # 既存の教員一覧を取得
    teachers = CustomUser.objects.filter(role='teacher').order_by('created_at')
    
    # 教員追加処理
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
                    if CustomUser.objects.filter(email=email).exists():
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
    
    context = {
        'teachers': teachers,
    }
    return render(request, 'school_management/admin_teacher_management.html', context)
