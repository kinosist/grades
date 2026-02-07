from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from ...models import ClassRoom, LessonSession

@login_required
def session_list_view(request, class_id):
    """授業回一覧"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    sessions = LessonSession.objects.filter(classroom=classroom).order_by('session_number')
    
    context = {
        'classroom': classroom,
        'sessions': sessions,
    }
    return render(request, 'school_management/session_list.html', context)