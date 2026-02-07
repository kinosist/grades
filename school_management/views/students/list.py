from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from ...models import Student

# 学生管理ビュー
@login_required
def student_list_view(request):
    """学生一覧（すべての学生）"""
    # 削除処理
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete_student':
            student_number = request.POST.get('student_number')
            if student_number:
                try:
                    student = Student.objects.get(student_number=student_number, role='student')
                    student_name = student.full_name
                    student.delete()
                    messages.success(request, f'{student_name}さんを削除しました。')
                    return redirect('school_management:student_list')
                except Student.DoesNotExist:
                    messages.error(request, '学生が見つかりません。')
                except Exception as e:
                    messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
    
    # すべての学生を表示
    students = Student.objects.filter(
        role='student',
        student_number__isnull=False,
        student_number__gt=''
    ).order_by('student_number')
    
    # 検索機能を追加
    search_query = request.GET.get('search', '')
    if search_query:
        students = students.filter(
            Q(student_number__icontains=search_query) |
            Q(full_name__icontains=search_query)
        )
    
    context = {
        'students': students,
        'search_query': search_query,
    }
    return render(request, 'school_management/student_list.html', context)