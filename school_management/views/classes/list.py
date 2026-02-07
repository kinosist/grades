from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from ...models import ClassRoom

@login_required
def class_list_view(request):
    """クラス一覧"""
    classes = ClassRoom.objects.filter(teachers=request.user)
    return render(request, 'school_management/class_list.html', {'classes': classes})