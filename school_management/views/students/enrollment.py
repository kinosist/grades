import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Q
from ...models import ClassRoom, CustomUser, Student, StudentClassPoints


@login_required
def bulk_student_add(request, class_id):
    """学生一括追加（既存学生から選択）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        selected_student_ids = request.POST.getlist('selected_students')
        if not selected_student_ids:
            messages.error(request, '追加する学生を選択してください。')
        else:
            added_count = 0
            for student_id in selected_student_ids:
                try:
                    student = CustomUser.objects.get(id=student_id, role='student')
                    if not classroom.students.filter(id=student.id).exists():
                        classroom.students.add(student)
                        # クラスポイントを0で初期化
                        StudentClassPoints.objects.get_or_create(
                            student=student,
                            classroom=classroom,
                            defaults={'points': 0}
                        )
                        added_count += 1
                except CustomUser.DoesNotExist:
                    continue
            
            if added_count > 0:
                messages.success(request, f'{added_count}人の学生をクラスに追加しました。')
                return redirect('school_management:class_detail', class_id=class_id)
            else:
                messages.warning(request, '追加された学生はいませんでした。')
    
    # 既にクラスに所属している学生を除外
    existing_student_ids = classroom.students.values_list('id', flat=True)
    available_students = CustomUser.objects.filter(
        role='student',
        student_number__isnull=False,
        student_number__gt=''
    ).exclude(id__in=existing_student_ids).order_by('student_number')
    
    # 検索機能
    search_query = request.GET.get('search', '')
    if search_query:
        available_students = available_students.filter(
            Q(student_number__icontains=search_query) |
            Q(full_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    context = {
        'classroom': classroom,
        'available_students': available_students,
        'search_query': search_query,
    }
    return render(request, 'school_management/class_student_select.html', context)


@login_required
def bulk_student_add_csv(request, class_id):
    """学生一括追加（CSV形式）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        student_data = request.POST.get('student_data', '').strip()
        
        if not student_data:
            messages.error(request, '学生データを入力してください。')
            return render(request, 'school_management/bulk_student_add.html', {'classroom': classroom})
        
        lines = student_data.split('\n')
        added_count = 0
        error_count = 0
        errors = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
                
            # タブまたはカンマで分割
            parts = line.replace('\t', ',').split(',')
            if len(parts) < 2:
                errors.append(f'行{line_num}: 形式が正しくありません - {line}')
                error_count += 1
                continue
            
            student_number = parts[0].strip()
            full_name = parts[1].strip()
            email = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
            
            try:
                # 重複チェック（学籍番号またはメールアドレス）
                if Student.objects.filter(student_number=student_number).exists():
                    errors.append(f'行{line_num}: 学生番号が既に存在します - {student_number}')
                    error_count += 1
                    continue
                    
                # メールアドレスの重複チェック（null値は除外）
                if email and Student.objects.filter(email=email).exists():
                    errors.append(f'行{line_num}: メールアドレスが既に存在します - {email}')
                    error_count += 1
                    continue
                
                # 学生作成（統合ユーザーモデル）
                student = Student.objects.create_user(
                    email=email,
                    full_name=full_name,
                    password='student123',  # デフォルトパスワード
                    role='student',
                    student_number=student_number,
                )
                # クラスに学生を追加
                classroom.students.add(student)
                # クラスポイントを0で初期化
                StudentClassPoints.objects.get_or_create(
                    student=student,
                    classroom=classroom,
                    defaults={'points': 0}
                )
                added_count += 1
                
            except Exception as e:
                errors.append(f'行{line_num}: エラー - {str(e)}')
                error_count += 1
        
        # 結果メッセージ
        if added_count > 0:
            messages.success(request, f'{added_count}人の学生を追加しました。')
        if error_count > 0:
            for error in errors[:5]:  # 最初の5個のエラーのみ表示
                messages.error(request, error)
            if len(errors) > 5:
                messages.error(request, f'他に{len(errors) - 5}個のエラーがあります。')
        
        if added_count > 0:
            return redirect('school_management:class_detail', class_id=class_id)
    
    context = {
        'classroom': classroom,
    }
    return render(request, 'school_management/bulk_student_add.html', context)

# クラスから学生を除籍
@login_required
@csrf_exempt
@require_POST
def remove_student_from_class(request, student_id):
    """学生をクラスから除籍する"""
    if request.method == 'POST' and request.headers.get('content-type') == 'application/json':
        try:
            import json
            data = json.loads(request.body)
            class_id = data.get('class_id')
            
            student = get_object_or_404(CustomUser, id=student_id, role='student')
            # 担当教師のチェックを追加
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
            
            # 学生をクラスから削除
            classroom.students.remove(student)
            
            return JsonResponse({'success': True, 'message': f'{student.full_name}さんをクラスから除籍しました'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': '不正なリクエストです'})