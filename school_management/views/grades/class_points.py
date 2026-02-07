import json
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from ...models import ClassRoom, CustomUser, StudentClassPoints, StudentLessonPoints

@login_required
@require_POST
def update_attendance_rate(request, class_id):
    """出席率を更新するAPI"""
    import json
    from django.views.decorators.csrf import csrf_exempt
    
    # JSONリクエストを受け取る
    data = json.loads(request.body)
    student_id = data.get('student_id')
    attendance_rate = data.get('attendance_rate')
    attendance_points = data.get('attendance_points', 0)
    
    # バリデーション
    if not student_id or attendance_rate is None:
        return JsonResponse({'success': False, 'error': 'パラメータが不足しています'})
    
    if not (0 <= attendance_rate <= 100):
        return JsonResponse({'success': False, 'error': '出席率は0〜100の範囲で入力してください'})
    
    # クラスと学生を取得
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, id=student_id)
    
    # 学生がクラスに所属しているか確認
    if not classroom.students.filter(id=student_id).exists():
        return JsonResponse({'success': False, 'error': 'この学生はクラスに所属していません'})
    
    # 出席率、出席点、合計点をデータベースに保存
    student_class_points, created = StudentClassPoints.objects.get_or_create(
        student=student,
        classroom=classroom,
        defaults={'points': 0, 'attendance_rate': attendance_rate, 'attendance_points': attendance_points}
    )
    
    if not created:
        # 既存のレコードの出席率、出席点を更新（ポイントは更新しない）
        student_class_points.attendance_rate = attendance_rate
        student_class_points.attendance_points = attendance_points
        student_class_points.save(update_fields=['attendance_rate', 'attendance_points'])
    else:
        student_class_points.save(update_fields=['attendance_rate', 'attendance_points'])
    
    return JsonResponse({'success': True, 'message': '出席率を保存しました'})

@login_required
def class_points_view(request, class_id):
    """クラスごとのポイント一覧"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all().order_by('student_number')
    
    # 各学生のクラス内成績を取得
    student_grades = []
    
    for student in students:
        # このクラスの授業回でのポイントを取得
        lesson_points = StudentLessonPoints.objects.filter(
            student=student,
            lesson_session__classroom=classroom
        ).select_related('lesson_session').order_by('lesson_session__session_number')
        
        total_class_points = sum(point.points for point in lesson_points)
        session_count = lesson_points.count()
        average_points = round(total_class_points / session_count, 1) if session_count > 0 else 0
        
        # 成績評価
        if average_points >= 5:
            grade_level = '優秀'
            grade_color = 'success'
        elif average_points >= 3:
            grade_level = '良好'
            grade_color = 'warning'
        elif average_points >= 1:
            grade_level = '普通'
            grade_color = 'info'
        else:
            grade_level = '要努力'
            grade_color = 'secondary'
        
        # クラス単位の合計ポイントを取得（StudentClassPoints があれば優先して表示）
        try:
            student_class_point = StudentClassPoints.objects.get(student=student, classroom=classroom).points
        except StudentClassPoints.DoesNotExist:
            student_class_point = None

        student_grades.append({
            'student': student,
            'total_points': total_class_points,
            'average_points': average_points,
            'session_count': session_count,
            'lesson_points': lesson_points,
            'grade_level': grade_level,
            'grade_color': grade_color,
            'overall_points': student.points,  # 全体のポイント（参考用）
            'class_points': student_class_point,  # クラス単位のポイント（あれば表示）
        })
    
    # 平均ポイント順でソート
    student_grades.sort(key=lambda x: x['average_points'], reverse=True)
    
    # クラス全体の統計
    total_students = len(student_grades)
    if total_students > 0:
        class_average = round(sum(grade['average_points'] for grade in student_grades) / total_students, 1)
        max_average = max(grade['average_points'] for grade in student_grades)
        min_average = min(grade['average_points'] for grade in student_grades)
    else:
        class_average = 0
        max_average = 0
        min_average = 0
    
    context = {
        'classroom': classroom,
        'student_grades': student_grades,
        'class_stats': {
            'total_students': total_students,
            'class_average': class_average,
            'max_average': max_average,
            'min_average': min_average,
        }
    }
    return render(request, 'school_management/class_points.html', context)