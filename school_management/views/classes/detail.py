from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.urls import reverse
from ...models import ClassRoom, LessonSession, PeerEvaluation, StudentClassPoints, PointColumn

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

    #  追加：このクラスの独自の評価項目（列）を取得
    point_columns = classroom.point_columns.all().order_by('created_at')

    context = {
        'classroom': classroom,
        'students': students,
        'lessons': lessons,
        'sessions': sessions,
        'peer_evaluations': peer_evaluations,
        'recent_lessons': lessons,
        'total_sessions': all_sessions.count(),
        'point_columns': point_columns,  #  テンプレートに渡す
    }
    return render(request, 'school_management/class_detail.html', context)

#  新規追加：評価項目の「追加」処理
@login_required
@require_POST
def add_point_column(request, class_id):
    """独自の評価項目を追加"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    column_title = request.POST.get('column_title', '').strip()
    
    if column_title:
        PointColumn.objects.create(classroom=classroom, column_title=column_title)
        messages.success(request, f'評価項目「{column_title}」を追加しました。')
    else:
        messages.error(request, '項目名を入力してください。')
        
    # 保存後は設定タブを開いた状態のままリダイレクト
    url = reverse('school_management:class_detail', args=[class_id])
    return redirect(f"{url}?active_tab=settings")

#  新規追加：評価項目の「削除」処理
@login_required
@require_POST
def delete_point_column(request, column_id):
    """独自の評価項目を削除"""
    # セキュリティ: 自分のクラスの項目しか削除できないようにする
    column = get_object_or_404(PointColumn, id=column_id, classroom__teachers=request.user)
    class_id = column.classroom.id
    title = column.column_title
    
    column.delete()
    messages.success(request, f'評価項目「{title}」を削除しました。')
    
    url = reverse('school_management:class_detail', args=[class_id])
    return redirect(f"{url}?active_tab=settings")