from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from ...models import ClassRoom, LessonSession, PeerEvaluation, StudentClassPoints

@login_required
def class_detail_view(request, class_id):
    """クラス詳細"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all()
    
    # すべての授業回を取得
    all_sessions = LessonSession.objects.filter(classroom=classroom).order_by('-date')
    
    # 常にすべての授業回を表示
    lessons = all_sessions
    sessions = all_sessions  # 授業回数表示用
    
    peer_evaluations = PeerEvaluation.objects.filter(lesson_session__classroom=classroom)
    
    # テンプレート側で複雑なクエリ呼び出しを避けるため、各 student に class_point を付与
    student_class_points = StudentClassPoints.objects.filter(classroom=classroom, student__in=students)
    scp_map = {scp.student_id: scp for scp in student_class_points}
    
    # 動的に属性を付与（テンプレートで student.class_point として参照できるようにする）
    for s in students:
        setattr(s, 'class_point', scp_map.get(s.id))

    context = {
        'classroom': classroom,
        'students': students,
        'lessons': lessons,
        'sessions': sessions,
        'peer_evaluations': peer_evaluations,
        'recent_lessons': lessons,
        'total_sessions': all_sessions.count(),
    }
    return render(request, 'school_management/class_detail.html', context)