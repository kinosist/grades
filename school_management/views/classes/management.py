from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.middleware.csrf import get_token
from django.contrib import messages
from ...models import ClassRoom

@login_required
def class_create_view(request):
    """クラス作成"""
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        class_name = request.POST.get('class_name')
        year = request.POST.get('year')
        semester = request.POST.get('semester')
        
        if class_name and year and semester:
            try:
                classroom = ClassRoom.objects.create(
                    class_name=class_name,
                    year=int(year),
                    semester=semester
                )
                # 担当教員として現在のユーザーを追加
                classroom.teachers.add(request.user)
                messages.success(request, 'クラスを作成しました。')
                return redirect('school_management:class_list')
            except ValueError:
                messages.error(request, '年度は数値で入力してください。')
        else:
            messages.error(request, '必須項目を入力してください。')
    
    return render(request, 'school_management/class_create.html', {'csrf_token': csrf_token})

@login_required
@require_POST
def class_delete_view(request, class_id):
    """クラス削除"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    try:
        class_name = classroom.class_name
        classroom.delete()
        messages.success(request, f'クラス「{class_name}」を削除しました。')
    except Exception as e:
        messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
        
    return redirect('school_management:class_list')