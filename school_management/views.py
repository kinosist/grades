from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.middleware.csrf import get_token
from django.db.models import Avg, Count, Q, Max
from django.db import models, IntegrityError
from django.utils import timezone
import qrcode
import io
import base64
from .models import ClassRoom, Student, Teacher, LessonSession, Quiz, QuizScore, PeerEvaluation, Attendance, Group, GroupMember, ContributionEvaluation, CustomUser, StudentQRCode, QRCodeScan, StudentLessonPoints, StudentClassPoints
from django.urls import reverse

def login_view(request):
    """ログイン画面"""
    # CSRFトークンを強制的に生成
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        remember = request.POST.get('remember')
        
        # カスタムユーザーモデルの場合、usernameフィールドがemailなのでemailで認証
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            if not remember:
                request.session.set_expiry(0)  # ブラウザ終了時にセッション終了
            messages.success(request, f'ようこそ、{user.full_name}さん！')
            
            # 役割に応じてリダイレクト先を変更
            if user.role == 'admin':
                return redirect('school_management:admin_teacher_management')
            elif user.is_teacher:
                return redirect('school_management:dashboard')
            elif user.is_student:
                return redirect('school_management:student_dashboard')
            else:
                return redirect('school_management:dashboard')
        else:
            messages.error(request, 'メールアドレスまたはパスワードが正しくありません。')
    
    return render(request, 'school_management/login_temp.html', {'csrf_token': csrf_token})

@csrf_exempt
def debug_login_view(request):
    """デバッグ用ログイン（CSRF無効）"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'ようこそ、{user.full_name}さん！')
            return redirect('school_management:dashboard')
        else:
            messages.error(request, 'メールアドレスまたはパスワードが正しくありません。')
    
    return render(request, 'school_management/login_temp.html')

def logout_view(request):
    """ログアウト"""
    logout(request)
    messages.info(request, 'ログアウトしました。')
    return redirect('school_management:login')

@login_required
def dashboard_view(request):
    """メインダッシュボード（役割に応じて振り分け）"""
    if request.user.role == 'admin':
        return redirect('school_management:admin_teacher_management')
    elif request.user.is_teacher:
        return teacher_dashboard(request)
    elif request.user.is_student:
        return student_dashboard(request)
    else:
        return redirect('school_management:login')


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


@login_required
def teacher_dashboard(request):
    """教員用ダッシュボード"""
    from .models import ClassRoom, LessonSession, Student
    
    # 担当クラス数
    user_classes = ClassRoom.objects.filter(teachers=request.user)
    total_classes = user_classes.count()
    
    # 担当クラスの学生数
    total_students = Student.objects.filter(classroom__teachers=request.user).distinct().count()
    
    # 今週の授業回数
    from datetime import datetime, timedelta
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    this_week_sessions = LessonSession.objects.filter(
        classroom__teachers=request.user,
        date__range=[week_start, week_end]
    ).count()
    
    # 最近の授業回
    recent_sessions = LessonSession.objects.filter(
        classroom__teachers=request.user
    ).order_by('-date')[:5]
    
    context = {
        'total_classes': total_classes,
        'total_students': total_students,
        'this_week_sessions': this_week_sessions,
        'recent_sessions': recent_sessions,
        'classes': user_classes,
    }
    
    return render(request, 'school_management/dashboard.html', context)


@login_required
def student_dashboard(request):
    """学生用ダッシュボード"""
    from .models import ClassRoom, LessonSession
    
    # 学生が所属するクラスを取得
    student_classrooms = ClassRoom.objects.filter(students=request.user)
    
    # 最近の授業回
    recent_sessions = LessonSession.objects.filter(
        classroom__in=student_classrooms
    ).order_by('-date')[:10]
    
    # ピア評価が必要な授業回
    pending_evaluations = LessonSession.objects.filter(
        classroom__in=student_classrooms,
        has_peer_evaluation=True
    ).order_by('-date')
    
    # 学生の授業ごとのポイントを取得
    lesson_points = StudentLessonPoints.objects.filter(
        student=request.user
    ).select_related('lesson_session').order_by('-lesson_session__date')
    
    # クラスごとのポイントを取得
    class_points_list = []
    for classroom in student_classrooms:
        try:
            class_points_obj = StudentClassPoints.objects.get(student=request.user, classroom=classroom)
            class_points = class_points_obj.points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        class_points_list.append({
            'classroom': classroom,
            'points': class_points
        })
    
    context = {
        'student_classrooms': student_classrooms,
        'recent_sessions': recent_sessions,
        'pending_evaluations': pending_evaluations,
        'total_classes': student_classrooms.count(),
        'lesson_points': lesson_points,
        'class_points_list': class_points_list,
    }
    return render(request, 'school_management/student_dashboard.html', context)

# クラス管理ビュー
@login_required
def class_list_view(request):
    """クラス一覧"""
    classes = ClassRoom.objects.filter(teachers=request.user)
    return render(request, 'school_management/class_list.html', {'classes': classes})

@login_required
def class_detail_view(request, class_id):
    """クラス詳細"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all()
    
    # すべての授業回を取得
    all_sessions = LessonSession.objects.filter(classroom=classroom).order_by('-date')
    
    # show_allパラメータで全件表示するかどうかを判断
    show_all = request.GET.get('show_all', 'false') == 'true'
    
    if show_all:
        lessons = all_sessions  # すべて表示
    else:
        lessons = all_sessions[:5]  # 上位5件のみ
    
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
        'sessions': sessions,  # 授業回数表示用
        'peer_evaluations': peer_evaluations,
        'recent_lessons': lessons,
        'show_all': show_all,
        'total_sessions': all_sessions.count(),
    }
    return render(request, 'school_management/class_detail.html', context)

@login_required
def class_create_view(request):
    """クラス作成"""
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        class_name = request.POST.get('class_name')
        year = request.POST.get('year')
        semester = request.POST.get('semester')
        
        if class_name and year and semester:
            classroom = ClassRoom.objects.create(
                class_name=class_name,
                year=int(year),
                semester=semester
            )
            # 担当教員として現在のユーザーを追加
            classroom.teachers.add(request.user)
            messages.success(request, 'クラスを作成しました。')
            return redirect('school_management:class_list')
        else:
            messages.error(request, '必須項目を入力してください。')
    
    return render(request, 'school_management/class_create.html', {'csrf_token': csrf_token})

# ============ セッション（授業回）管理 ============

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

@login_required
def session_create_view(request, class_id):
    """授業回作成"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        session_number = request.POST.get('session_number')
        date = request.POST.get('date')
        topic = request.POST.get('topic')
        
        if session_number and date:
            try:
                session = LessonSession.objects.create(
                    classroom=classroom,
                    session_number=int(session_number),
                    date=date,
                    topic=topic or ''
                )
                messages.success(request, f'第{session_number}回授業を作成しました。')
                return redirect('school_management:session_detail', session_id=session.id)
            except (ValueError, Exception) as e:
                messages.error(request, f'作成に失敗しました: {str(e)}')
        else:
            messages.error(request, '授業回と日付は必須です。')
    
    # 次の授業回番号を提案
    last_session = LessonSession.objects.filter(classroom=classroom).order_by('-session_number').first()
    next_session_number = (last_session.session_number + 1) if last_session else 1
    
    context = {
        'classroom': classroom,
        'next_session_number': next_session_number,
    }
    return render(request, 'school_management/session_create.html', context)

@login_required
def session_detail_view(request, session_id):
    """授業回詳細"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    quizzes = Quiz.objects.filter(lesson_session=session)
    
    context = {
        'session': session,
        'quizzes': quizzes,
    }
    return render(request, 'school_management/session_detail.html', context)

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

@login_required
def student_detail_view(request, student_number):
    """学生詳細"""
    student = get_object_or_404(CustomUser, student_number=student_number, role='student')
    
    # 削除処理
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete_student':
            try:
                student_name = student.full_name
                student.delete()
                messages.success(request, f'{student_name}さんを削除しました。')
                return redirect('school_management:student_list')
            except Exception as e:
                messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
                return redirect('school_management:student_detail', student_number=student_number)
    
    # 所属クラス一覧とそれぞれのクラスポイントを取得（担当クラスのみ）
    classes = student.classroom_set.filter(teachers=request.user)
    
    # 担当クラスに所属していない場合は、すべてのクラスを表示（アクセス制御を緩和）
    if not classes.exists():
        classes = student.classroom_set.all()
    
    class_data = []
    for classroom in classes:
        try:
            class_points_obj = StudentClassPoints.objects.get(student=student, classroom=classroom)
            class_points = class_points_obj.points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        class_data.append({
            'classroom': classroom,
            'points': class_points
        })
    
    context = {
        'student': student,
        'classes': classes,
        'class_data': class_data,
    }
    return render(request, 'school_management/student_detail.html', context)

@login_required
def class_student_detail_view(request, class_id, student_number):
    """クラス内の学生詳細"""
    # 担当教師のチェックを追加
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, student_number=student_number, role='student')
    
    # 学生がこのクラスに所属しているかチェック
    if not classroom.students.filter(student_number=student_number).exists():
        messages.error(request, 'この学生は指定されたクラスに所属していません。')
        return redirect('school_management:class_detail', class_id=class_id)
    
    # クラス内での学生の成績やアクティビティを取得
    class_sessions = LessonSession.objects.filter(classroom=classroom).order_by('-date')
    
    # このクラスでのクイズ成績を取得
    quiz_scores = QuizScore.objects.filter(
        student=student,
        quiz__lesson_session__classroom=classroom
    ).select_related('quiz', 'quiz__lesson_session').order_by('-quiz__lesson_session__date')
    
    # このクラスでの出席記録を取得
    attendance_records = Attendance.objects.filter(
        student=student,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('-lesson_session__date')
    
    # このクラスでのピア評価を取得（学生が所属するグループによる評価）
    # まず学生が所属するグループを取得
    student_groups = GroupMember.objects.filter(student=student).values_list('group', flat=True)
    
    peer_evaluations = PeerEvaluation.objects.filter(
        evaluator_group__in=student_groups,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('-created_at')
    
    # 統計情報を計算
    total_quizzes = quiz_scores.count()
    avg_score = quiz_scores.aggregate(avg=Avg('score'))['avg'] or 0
    attendance_count = attendance_records.filter(status='present').count()
    total_sessions = class_sessions.count()
    attendance_rate = (attendance_count / total_sessions * 100) if total_sessions > 0 else 0
    
    context = {
        'classroom': classroom,
        'student': student,
        'class_sessions': class_sessions[:5],  # 最新5セッション
        'quiz_scores': quiz_scores[:10],  # 最新10件のクイズ成績
        'attendance_records': attendance_records[:10],  # 最新10件の出席記録
        'peer_evaluations': peer_evaluations[:10],  # 最新10件のピア評価
        'stats': {
            'total_quizzes': total_quizzes,
            'avg_score': round(avg_score, 1),
            'attendance_count': attendance_count,
            'total_sessions': total_sessions,
            'attendance_rate': round(attendance_rate, 1),
        }
    }
    return render(request, 'school_management/class_student_detail.html', context)

@login_required
def student_edit_view(request, student_number):
    """学生編集"""
    student = get_object_or_404(CustomUser, student_number=student_number, role='student')
    
    # アクセス制御を緩和（すべての学生を編集可能に）
    # 必要に応じて、管理者権限チェックを追加することも可能
    
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        # フォームデータの取得
        full_name = request.POST.get('full_name')
        furigana = request.POST.get('furigana')
        email = request.POST.get('email')
        points = request.POST.get('points')
        
        # バリデーション
        if not full_name or not furigana:
            messages.error(request, '氏名とふりがなは必須項目です。')
        else:
            try:
                # 学生情報を更新
                student.full_name = full_name
                student.furigana = furigana
                student.email = email or ''
                
                # ポイントはクラス単位で管理するため、ここでは更新しない
                # クラス詳細画面から各クラスのポイントを個別に更新する
                
                student.save()
                messages.success(request, f'{student.full_name}さんの情報を更新しました。')
                return redirect('school_management:student_detail', student_number=student.student_number)
                
            except Exception as e:
                messages.error(request, f'更新中にエラーが発生しました: {str(e)}')
    
    context = {
        'student': student,
        'csrf_token': csrf_token,
    }
    return render(request, 'school_management/student_edit.html', context)

@login_required
def student_create_view(request):
    """学生作成（単体・一括対応）"""
    # デバッグ用: ログイン状態をチェック
    if not request.user.is_authenticated:
        return redirect('school_management:login')
    
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        registration_type = request.POST.get('registration_type', 'single')
        
        if registration_type == 'bulk':
            # 一括登録処理
            bulk_student_data = request.POST.get('bulk_student_data', '').strip()
            
            if not bulk_student_data:
                messages.error(request, '学生データを入力してください。')
                return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
            
            lines = bulk_student_data.split('\n')
            added_count = 0
            error_count = 0
            errors = []
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue
                
                # カンマで分割
                parts = [part.strip() for part in line.split(',')]
                if len(parts) < 3:
                    errors.append(f'行{line_num}: 必要な項目が不足しています（学籍番号,氏名,ふりがな） - {line}')
                    error_count += 1
                    continue
                
                student_number = parts[0]
                full_name = parts[1]
                furigana = parts[2]
                email = parts[3] if len(parts) > 3 and parts[3].strip() else None
                
                try:
                    # 重複チェック
                    if Student.objects.filter(student_number=student_number).exists():
                        errors.append(f'行{line_num}: 学籍番号 "{student_number}" は既に登録されています')
                        error_count += 1
                        continue
                    
                    # メールアドレスの重複チェック（null値は除外）
                    if email and Student.objects.filter(email=email).exists():
                        errors.append(f'行{line_num}: メールアドレス "{email}" は既に登録されています')
                        error_count += 1
                        continue
                    
                    # 学生作成
                    # デフォルトパスワードを生成（学籍番号をベースに）
                    default_password = f"student_{student_number}"
                    
                    Student.objects.create_user(
                        email=email,
                        full_name=full_name,
                        password=default_password,
                        student_number=student_number,
                        furigana=furigana,
                        role='student'
                    )
                    added_count += 1
                    
                except IntegrityError as e:
                    # データベース制約違反の場合
                    error_message = str(e).lower()
                    if 'student_number' in error_message or 'unique constraint' in error_message:
                        errors.append(f'行{line_num}: 学籍番号 "{student_number}" は既に登録されています')
                    elif 'email' in error_message:
                        errors.append(f'行{line_num}: メールアドレス "{email}" は既に登録されています')
                    else:
                        errors.append(f'行{line_num}: データの重複により登録できませんでした')
                    error_count += 1
                    
                except Exception as e:
                    errors.append(f'行{line_num}: 作成エラー - {str(e)}')
                    error_count += 1
            
            # 結果メッセージ
            if added_count > 0:
                messages.success(request, f'{added_count}名の学生を一括登録しました。')
            if error_count > 0:
                for error in errors[:10]:  # 最初の10個のエラーのみ表示
                    messages.error(request, error)
                if len(errors) > 10:
                    messages.error(request, f'他に{len(errors) - 10}個のエラーがあります。')
            
            if added_count > 0:
                return redirect('school_management:student_list')
        
        else:
            # 単体登録処理（既存の処理）
            student_number = request.POST.get('student_number')
            full_name = request.POST.get('full_name')
            furigana = request.POST.get('furigana')
            email = request.POST.get('email')
            
            if student_number and full_name and furigana:
                # メールアドレスを空文字列の場合はNoneに変換
                email = email.strip() if email and email.strip() else None
                
                try:
                    # 学籍番号の重複チェック
                    if Student.objects.filter(student_number=student_number).exists():
                        messages.error(request, f'学籍番号 "{student_number}" は既に登録されています。別の学籍番号を入力してください。')
                        return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
                    
                    # メールアドレスの重複チェック（null値は除外）
                    if email and Student.objects.filter(email=email).exists():
                        messages.error(request, f'メールアドレス "{email}" は既に登録されています。別のメールアドレスを入力してください。')
                        return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
                    
                    # 学生作成
                    # デフォルトパスワードを生成（学籍番号をベースに）
                    default_password = f"student_{student_number}"
                    
                    Student.objects.create_user(
                        email=email,
                        full_name=full_name,
                        password=default_password,
                        student_number=student_number,
                        furigana=furigana,
                        role='student'
                    )
                    messages.success(request, f'{full_name}さん（学籍番号: {student_number}）を追加しました。')
                    return redirect('school_management:student_list')
                    
                except IntegrityError as e:
                    # データベース制約違反の場合
                    error_message = str(e).lower()
                    if 'student_number' in error_message or 'unique constraint' in error_message:
                        messages.error(request, f'学籍番号 "{student_number}" は既に登録されています。別の学籍番号を入力してください。')
                    elif 'email' in error_message:
                        messages.error(request, f'メールアドレス "{email}" は既に登録されています。別のメールアドレスを入力してください。')
                    else:
                        messages.error(request, 'データの重複により登録できませんでした。入力内容を確認してください。')
                    return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
                    
                except Exception as e:
                    messages.error(request, f'学生の追加中にエラーが発生しました: {str(e)}')
                    return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})
            else:
                messages.error(request, '必須項目を入力してください。')
    
    return render(request, 'school_management/student_create.html', {'csrf_token': csrf_token})

# ピア評価ビュー
@login_required
def peer_evaluation_list_view(request, session_id):
    """ピア評価一覧"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    evaluations = session.peerevaluation_set.all()
    
    context = {
        'session': session,
        'evaluations': evaluations,
    }
    return render(request, 'school_management/peer_evaluation_list.html', context)

@login_required 
def peer_evaluation_create_view(request, session_id):
    """ピア評価作成・設定"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    csrf_token = get_token(request)
    
    if request.method == 'POST':
        # ピア評価を有効にする
        session.has_peer_evaluation = True
        session.save()
        messages.success(request, 'ピア評価を有効にしました。評価リンクを学生に共有してください。')
        return redirect('school_management:peer_evaluation_list', session_id=session.id)
    
    context = {
        'session': session,
        'csrf_token': csrf_token,
    }
    return render(request, 'school_management/peer_evaluation_create.html', context)

def peer_evaluation_form_view(request, token):
    """匿名ピア評価フォーム（学生用）"""
    # トークンからセッション情報を取得（簡易実装）
    import hashlib
    
    try:
        # トークンの検証とセッション取得
        for session in LessonSession.objects.filter(has_peer_evaluation=True):
            session_token = hashlib.md5(f"peer_{session.id}".encode()).hexdigest()
            if session_token == token:
                target_session = session
                break
        else:
            messages.error(request, '無効なリンクです。')
            return redirect('school_management:login')
            
        # グループ取得
        groups = target_session.group_set.all()
        
        if request.method == 'POST':
            # フォームデータの処理
            evaluator_group_name = request.POST.get('evaluator_group')
            first_place_group = request.POST.get('first_place_group')
            second_place_group = request.POST.get('second_place_group')
            first_place_reason = request.POST.get('first_place_reason')
            second_place_reason = request.POST.get('second_place_reason')
            general_comment = request.POST.get('general_comment')
            
            # メンバー評価の処理
            member_evaluations = []
            for i in range(1, 8):  # 最大7名のメンバー
                member_name = request.POST.get(f'member_{i}_name')
                member_score = request.POST.get(f'member_{i}_score')
                
                if member_name and member_score:
                    member_evaluations.append({
                        'name': member_name,
                        'score': int(member_score)
                    })
            
            # 評価データを保存（簡易実装）
            from .models import PeerEvaluation
            
            # 評価グループを特定
            try:
                evaluator_group_obj = groups.filter(group_number=int(evaluator_group_name.replace('グループ', ''))).first()
            except:
                evaluator_group_obj = None
            
            # 1位グループを特定
            try:
                first_group_obj = groups.filter(group_number=int(first_place_group.replace('グループ', ''))).first()
            except:
                first_group_obj = None
                
            # 2位グループを特定  
            try:
                second_group_obj = groups.filter(group_number=int(second_place_group.replace('グループ', ''))).first()
            except:
                second_group_obj = None
            
            # ピア評価を保存
            evaluation = PeerEvaluation.objects.create(
                lesson_session=target_session,
                evaluator_group=evaluator_group_obj,
                first_place_group=first_group_obj,
                second_place_group=second_group_obj,
                first_place_reason=first_place_reason,
                second_place_reason=second_place_reason,
                general_comment=general_comment
            )
            
            # メンバー評価を保存
            if evaluator_group_obj:
                from .models import ContributionEvaluation, Student
                for member_eval in member_evaluations:
                    # 学生を名前で検索（簡易実装）
                    try:
                        student = Student.objects.filter(full_name__icontains=member_eval['name']).first()
                        if student:
                            ContributionEvaluation.objects.create(
                                peer_evaluation=evaluation,
                                evaluatee=student,
                                contribution_score=member_eval['score']
                            )
                    except:
                        pass
            
            return render(request, 'school_management/peer_evaluation_success.html', {
                'session': target_session
            })
        
        context = {
            'session': target_session,
            'groups': groups,
            'token': token,
        }
        return render(request, 'school_management/peer_evaluation_form.html', context)
        
    except Exception as e:
        messages.error(request, 'エラーが発生しました。')
        return redirect('school_management:login')

@login_required
def peer_evaluation_link_view(request, session_id):
    """ピア評価リンク生成"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    # 匿名トークン生成
    import hashlib
    token = hashlib.md5(f"peer_{session.id}".encode()).hexdigest()
    
    context = {
        'session': session,
        'token': token,
        'evaluation_url': request.build_absolute_uri(f'/peer-evaluation/{token}/')
    }
    return render(request, 'school_management/peer_evaluation_link.html', context)

@login_required
def peer_evaluation_results_view(request, session_id):
    """ピア評価結果表示"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    evaluations = session.peerevaluation_set.all()
    
    # 結果集計
    group_votes = {}
    contribution_scores = {}
    
    for evaluation in evaluations:
        # グループ投票集計
        if evaluation.first_place_group:
            group_name = f"グループ{evaluation.first_place_group.group_number}"
            if group_name not in group_votes:
                group_votes[group_name] = {'first': 0, 'second': 0}
            group_votes[group_name]['first'] += 1
            
        if evaluation.second_place_group:
            group_name = f"グループ{evaluation.second_place_group.group_number}"
            if group_name not in group_votes:
                group_votes[group_name] = {'first': 0, 'second': 0}
            group_votes[group_name]['second'] += 1
        
        # 貢献度評価集計
        for contrib_eval in evaluation.contributionevaluation_set.all():
            student_name = contrib_eval.evaluatee.full_name
            if student_name not in contribution_scores:
                contribution_scores[student_name] = []
            contribution_scores[student_name].append(contrib_eval.contribution_score)
    
    # 平均貢献度計算
    avg_contribution_scores = {}
    for student, scores in contribution_scores.items():
        avg_contribution_scores[student] = sum(scores) / len(scores)

    # グループ別集計（新テンプレート用）
    groups = session.group_set.all()
    group_stats = {}
    
    for group in groups:
        # このグループが1位に選ばれた回数
        first_place_votes = evaluations.filter(first_place_group=group).count()
        # このグループが2位に選ばれた回数
        second_place_votes = evaluations.filter(second_place_group=group).count()
        # このグループが評価した回数
        evaluations_given = evaluations.filter(evaluator_group=group).count()
        
        group_stats[group.id] = {
            'group': group,
            'first_place_votes': first_place_votes,
            'second_place_votes': second_place_votes,
            'total_votes': first_place_votes + second_place_votes,
            'evaluations_given': evaluations_given,
            'score': first_place_votes * 2 + second_place_votes  # 1位=2点、2位=1点でスコア計算
        }
    
    # スコア順でソート
    sorted_groups = sorted(group_stats.values(), key=lambda x: x['score'], reverse=True)
    
    context = {
        'lesson_session': session,  # テンプレートとの整合性を保つためにキー名を変更
        'evaluations': evaluations,
        'group_votes': group_votes,
        'avg_contribution_scores': avg_contribution_scores,
        'group_stats': sorted_groups,  # 新テンプレート用
        'total_evaluations': evaluations.count(),  # 新テンプレート用
        'total_groups': groups.count(),  # 新テンプレート用
    }
    return render(request, 'school_management/peer_evaluation_results.html', context)


# ============ 小テスト機能 ============

@login_required
def quiz_list_view(request, session_id):
    """小テスト一覧"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    quizzes = Quiz.objects.filter(lesson_session=session).order_by('created_at')
    
    context = {
        'session': session,
        'quizzes': quizzes,
    }
    return render(request, 'school_management/quiz_list.html', context)

@login_required
def quiz_create_view(request, session_id):
    """小テスト作成"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        quiz_name = request.POST.get('quiz_name')
        max_score = request.POST.get('max_score')
        grading_method = request.POST.get('grading_method')
        
        if quiz_name and max_score and grading_method:
            try:
                quiz = Quiz.objects.create(
                    lesson_session=session,
                    quiz_name=quiz_name,
                    max_score=int(max_score),
                    grading_method=grading_method
                )
                # セッションの小テストフラグを更新
                session.has_quiz = True
                session.save()
                
                messages.success(request, f'小テスト「{quiz_name}」を作成しました。')
                return redirect('school_management:quiz_grading', quiz_id=quiz.id)
            except ValueError:
                messages.error(request, '満点は数値で入力してください。')
        else:
            messages.error(request, 'すべての項目を入力してください。')
    
    context = {
        'session': session,
        'grading_methods': Quiz.GRADING_METHOD_CHOICES,
    }
    return render(request, 'school_management/quiz_create.html', context)

@login_required
def quiz_grading_view(request, quiz_id):
    """小テスト採点"""
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson_session__classroom__teachers=request.user)
    students = quiz.lesson_session.classroom.students.all()
    
    # 採点結果を学生IDをキーにして辞書作成
    score_objects = QuizScore.objects.filter(quiz=quiz, is_cancelled=False).select_related('student')
    scores = {score.student.student_number: score for score in score_objects}
    
    # 学生リストに採点情報を追加
    students_with_scores = []
    for student in students:
        student_data = {
            'student': student,
            'score': scores.get(student.student_number),
            'is_graded': student.student_number in scores
        }
        students_with_scores.append(student_data)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save_scores':
            # 採点結果保存
            teacher = request.user  # 現在のユーザーを採点者として使用
            
            for student in students:
                score_value = request.POST.get(f'score_{student.student_number}')
                if score_value and score_value.strip():
                    try:
                        score = int(score_value)
                        if 0 <= score <= quiz.max_score:
                            # 既存の採点結果があれば削除
                            QuizScore.objects.filter(quiz=quiz, student=student, is_cancelled=False).update(is_cancelled=True)
                            # 新しい採点結果を作成
                            QuizScore.objects.create(
                                quiz=quiz,
                                student=student,
                                score=score,
                                graded_by=teacher
                            )
                    except ValueError:
                        pass  # 無効な値は無視
            
            messages.success(request, '採点結果を保存しました。')
            return redirect('school_management:quiz_grading', quiz_id=quiz_id)
    
    context = {
        'quiz': quiz,
        'students_with_scores': students_with_scores,
        'students': students,
        'graded_count': len(scores),
        'quick_buttons': quiz.quick_buttons or {},
    }
    return render(request, 'school_management/quiz_grading.html', context)

@login_required
def quiz_results_view(request, quiz_id):
    """小テスト結果表示"""
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson_session__classroom__teachers=request.user)
    scores = QuizScore.objects.filter(quiz=quiz, is_cancelled=False).select_related('student').order_by('student__student_number')
    
    # 統計情報計算
    score_values = [score.score for score in scores]
    stats = {}
    if score_values:
        stats = {
            'count': len(score_values),
            'average': sum(score_values) / len(score_values),
            'max': max(score_values),
            'min': min(score_values),
            'total_students': quiz.lesson_session.classroom.students.count(),
            'graded_students': len(score_values),
        }
    
    context = {
        'quiz': quiz,
        'scores': scores,
        'stats': stats,
    }
    return render(request, 'school_management/quiz_results.html', context)


@login_required
def question_create_view(request, quiz_id):
    """小テスト問題作成"""
    from .models import Question, QuestionChoice
    
    quiz = get_object_or_404(Quiz, id=quiz_id)
    
    # 小テストの所属する授業回の教員かどうか確認
    if not quiz.lesson_session.classroom.teachers.filter(id=request.user.id).exists():
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        question_text = request.POST.get('question_text')
        question_type = request.POST.get('question_type')
        points = int(request.POST.get('points', 1))
        
        # 問題の順番を決定
        last_order = Question.objects.filter(quiz=quiz).aggregate(
            max_order=Max('order')
        )['max_order'] or 0
        
        question = Question.objects.create(
            quiz=quiz,
            question_text=question_text,
            question_type=question_type,
            points=points,
            order=last_order + 1
        )
        
        # 選択問題または正誤問題の場合、選択肢を作成
        if question_type in ['multiple_choice', 'true_false']:
            if question_type == 'true_false':
                # 正誤問題の場合、True/Falseの選択肢を自動作成
                QuestionChoice.objects.create(
                    question=question,
                    choice_text='正しい',
                    is_correct=request.POST.get('correct_answer') == 'true',
                    order=1
                )
                QuestionChoice.objects.create(
                    question=question,
                    choice_text='間違い',
                    is_correct=request.POST.get('correct_answer') == 'false',
                    order=2
                )
            else:
                # 選択問題の場合、入力された選択肢を作成
                choice_texts = request.POST.getlist('choice_text')
                correct_choice_index = int(request.POST.get('correct_choice', 0))
                
                for i, choice_text in enumerate(choice_texts):
                    if choice_text.strip():  # 空でない選択肢のみ作成
                        QuestionChoice.objects.create(
                            question=question,
                            choice_text=choice_text.strip(),
                            is_correct=(i == correct_choice_index),
                            order=i + 1
                        )
        
        # 記述問題の場合、正解を保存
        elif question_type == 'short_answer':
            question.correct_answer = request.POST.get('correct_answer', '')
            question.save()
        
        messages.success(request, f'問題「{question_text[:30]}...」を作成しました。')
        return redirect('school_management:question_manage', quiz_id=quiz.id)
    
    # 既存の問題一覧を取得
    questions = Question.objects.filter(quiz=quiz).prefetch_related('choices')
    
    context = {
        'quiz': quiz,
        'questions': questions,
    }
    return render(request, 'school_management/question_create.html', context)


@login_required
def question_manage_view(request, quiz_id):
    """小テスト問題管理"""
    from .models import Question
    
    quiz = get_object_or_404(Quiz, id=quiz_id)
    
    # 小テストの所属する授業回の教員かどうか確認
    if not quiz.lesson_session.classroom.teachers.filter(id=request.user.id).exists():
        return redirect('school_management:dashboard')
    
    questions = Question.objects.filter(quiz=quiz).prefetch_related('choices')
    
    # 合計配点を計算
    total_points = sum(question.points for question in questions)
    
    context = {
        'quiz': quiz,
        'questions': questions,
        'total_points': total_points,
    }
    return render(request, 'school_management/question_manage.html', context)


# 授業セッション管理
@login_required
def lesson_session_create(request, class_id):
    """授業回作成"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        session_number = request.POST.get('session_number')
        date = request.POST.get('date')
        topic = request.POST.get('topic', '')
        has_quiz = request.POST.get('has_quiz') == 'on'
        has_peer_evaluation = request.POST.get('has_peer_evaluation') == 'on'
        
        # 授業回作成
        lesson_session = LessonSession.objects.create(
            classroom=classroom,
            session_number=session_number,
            date=date,
            topic=topic,
            has_quiz=has_quiz,
            has_peer_evaluation=has_peer_evaluation
        )
        
        messages.success(request, f'第{session_number}回の授業を作成しました。')
        return redirect('school_management:class_detail', class_id=class_id)
    
    # 次の回数を自動設定
    last_session = LessonSession.objects.filter(classroom=classroom).order_by('-session_number').first()
    next_session_number = (last_session.session_number + 1) if last_session else 1
    
    context = {
        'classroom': classroom,
        'next_session_number': next_session_number,
    }
    return render(request, 'school_management/lesson_session_create.html', context)


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


@login_required
def lesson_session_detail(request, session_id):
    """授業回詳細"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    context = {
        'lesson_session': lesson_session,
    }
    return render(request, 'school_management/lesson_session_detail.html', context)


@login_required
def group_list_view(request, session_id):
    """グループ一覧表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student').order_by('group_number')
    
    # グループ統計情報を計算
    group_stats = []
    for group in groups:
        member_count = group.groupmember_set.count()
        group_stats.append({
            'group': group,
            'member_count': member_count,
            'members': group.groupmember_set.all()
        })
    
    context = {
        'lesson_session': lesson_session,
        'group_stats': group_stats,
        'total_students': lesson_session.classroom.students.count(),
        'assigned_students': sum(stat['member_count'] for stat in group_stats),
    }
    return render(request, 'school_management/group_list.html', context)

@login_required
def group_detail_view(request, session_id, group_id):
    """グループ詳細表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    group = get_object_or_404(Group, id=group_id, lesson_session=lesson_session)
    members = group.groupmember_set.all().select_related('student')
    
    context = {
        'lesson_session': lesson_session,
        'group': group,
        'members': members,
    }
    return render(request, 'school_management/group_detail.html', context)

@login_required
def group_management(request, session_id):
    """グループマスタ編集"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    students = lesson_session.classroom.students.all()
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student')
    
    if request.method == 'POST':
        # デバッグ用：送信されたPOSTデータを確認
        print("POST data:", dict(request.POST))
        
        # 既存のグループを削除
        Group.objects.filter(lesson_session=lesson_session).delete()
        
        # グループ数を取得
        group_count = int(request.POST.get('group_count', 0))
        
        for group_num in range(1, group_count + 1):
            # グループ名を取得
            group_name = request.POST.get(f'group_{group_num}_name', '').strip()
            
            group = Group.objects.create(
                lesson_session=lesson_session,
                group_number=group_num,
                group_name=group_name if group_name else f'グループ{group_num}'
            )
            
            # グループメンバーを追加
            member_keys = [key for key in request.POST.keys() if key.startswith(f'group_{group_num}_member_')]
            print(f"Group {group_num} member keys:", member_keys)
            
            for key in member_keys:
                student_id = request.POST.get(key)
                if student_id:
                    try:
                        student = CustomUser.objects.get(student_number=student_id, role='student')
                        role = request.POST.get(f'group_{group_num}_role_{key.split("_")[-1]}', '')
                        GroupMember.objects.create(
                            group=group,
                            student=student,
                            role=role
                        )
                        print(f"Added student {student_id} to group {group_num}")
                    except CustomUser.DoesNotExist:
                        messages.warning(request, f'学籍番号 {student_id} の学生が見つかりません。')
        
        messages.success(request, 'グループ編成を保存しました。')
        return redirect('school_management:group_list', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
        'students': students,
        'groups': groups,
    }
    return render(request, 'school_management/group_management.html', context)

@login_required
def group_edit_view(request, session_id, group_id):
    """グループ編集"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    group = get_object_or_404(Group, id=group_id, lesson_session=lesson_session)
    members = group.groupmember_set.all().select_related('student')
    available_students = lesson_session.classroom.students.exclude(
        id__in=members.values_list('student_id', flat=True)
    )
    
    if request.method == 'POST':
        # グループ名の更新
        group_name = request.POST.get('group_name', '').strip()
        group.group_name = group_name if group_name else f'グループ{group.group_number}'
        group.save()
        
        # メンバーの更新
        if 'action' in request.POST:
            action = request.POST.get('action')
            
            if action == 'add_member':
                student_id = request.POST.get('student_id')
                role = request.POST.get('role', '')
                if student_id:
                    try:
                        student = CustomUser.objects.get(id=student_id, role='student')
                        GroupMember.objects.create(
                            group=group,
                            student=student,
                            role=role
                        )
                        messages.success(request, f'{student.full_name}さんをグループに追加しました。')
                    except CustomUser.DoesNotExist:
                        messages.error(request, '学生が見つかりません。')
            
            elif action == 'remove_member':
                member_id = request.POST.get('member_id')
                if member_id:
                    try:
                        member = GroupMember.objects.get(id=member_id, group=group)
                        student_name = member.student.full_name
                        member.delete()
                        messages.success(request, f'{student_name}さんをグループから削除しました。')
                    except GroupMember.DoesNotExist:
                        messages.error(request, 'メンバーが見つかりません。')
            
            elif action == 'update_role':
                member_id = request.POST.get('member_id')
                new_role = request.POST.get('new_role', '')
                if member_id:
                    try:
                        member = GroupMember.objects.get(id=member_id, group=group)
                        member.role = new_role
                        member.save()
                        messages.success(request, '役割を更新しました。')
                    except GroupMember.DoesNotExist:
                        messages.error(request, 'メンバーが見つかりません。')
        
        return redirect('school_management:group_edit', session_id=session_id, group_id=group_id)
    
    context = {
        'lesson_session': lesson_session,
        'group': group,
        'members': members,
        'available_students': available_students,
    }
    return render(request, 'school_management/group_edit.html', context)

@login_required
def group_delete_view(request, session_id, group_id):
    """グループ削除"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    group = get_object_or_404(Group, id=group_id, lesson_session=lesson_session)
    
    if request.method == 'POST':
        group_name = group.display_name
        group.delete()
        messages.success(request, f'グループ「{group_name}」を削除しました。')
        return redirect('school_management:group_list', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
        'group': group,
    }
    return render(request, 'school_management/group_delete.html', context)


@login_required
def improved_peer_evaluation_create(request, session_id):
    """改善されたピア評価作成"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    groups = Group.objects.filter(lesson_session=lesson_session)
    
    if not groups.exists():
        messages.error(request, 'ピア評価を作成する前に、まずグループを設定してください。')
        return redirect('school_management:group_management', session_id=session_id)
    
    if request.method == 'POST':
        # 各グループに対してトークンを生成
        for group in groups:
            import uuid
            token = str(uuid.uuid4())
            
            # ピア評価レコードを作成（グループごと）
            PeerEvaluation.objects.create(
                lesson_session=lesson_session,
                evaluator_token=token,
                evaluator_group=group,
                # 仮の値を設定（後でフォームで更新）
                first_place_group=groups.first(),
                second_place_group=groups.first()
            )
        
        messages.success(request, 'ピア評価フォームを作成しました。')
        return redirect('school_management:peer_evaluation_links', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'students': lesson_session.classroom.students.all(),
    }
    return render(request, 'school_management/improved_peer_evaluation_create.html', context)


@login_required
def peer_evaluation_links(request, session_id):
    """ピア評価リンク一覧"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    evaluations = PeerEvaluation.objects.filter(
        lesson_session=lesson_session, 
        evaluator_group__isnull=False
    ).select_related('evaluator_group')
    
    context = {
        'lesson_session': lesson_session,
        'evaluations': evaluations,
    }
    return render(request, 'school_management/peer_evaluation_links.html', context)
    
def peer_evaluation_common_form(request, session_id):
    """共通ピア評価フォーム"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student')
    
    # 締切チェック
    is_closed = lesson_session.peer_evaluation_closed
    
    if request.method == 'POST' and not is_closed:
        # フォームデータの処理
        evaluator_group_id = request.POST.get('evaluator_group')
        participant_count = int(request.POST.get('participant_count', 0))
        first_place_group_id = request.POST.get('first_place_group')
        second_place_group_id = request.POST.get('second_place_group')
        first_place_reason = request.POST.get('first_place_reason', '')
        second_place_reason = request.POST.get('second_place_reason', '')
        general_comment = request.POST.get('general_comment', '')
        
        if evaluator_group_id and first_place_group_id and second_place_group_id:
            evaluator_group = get_object_or_404(Group, id=evaluator_group_id)
            first_place_group = get_object_or_404(Group, id=first_place_group_id)
            second_place_group = get_object_or_404(Group, id=second_place_group_id)
            
            # ピア評価を作成
            import uuid
            peer_evaluation = PeerEvaluation.objects.create(
                lesson_session=lesson_session,
                evaluator_token=str(uuid.uuid4()),
                evaluator_group=evaluator_group,
                first_place_group=first_place_group,
                second_place_group=second_place_group,
                first_place_reason=first_place_reason,
                second_place_reason=second_place_reason,
                general_comment=general_comment
            )
            
            # 貢献度評価を保存
            for i in range(participant_count):
                participant_member_id = request.POST.get(f'participant_{i}_member')
                contribution_score = request.POST.get(f'participant_{i}_contribution')
                
                if participant_member_id and contribution_score:
                    # 貢献度評価を保存（新しいモデルが必要な場合は作成）
                    # 今回は簡単のため、追加のモデルなしで処理
                    pass
            
            return render(request, 'school_management/peer_evaluation_thanks.html', {
                'lesson_session': lesson_session,
                'first_place_group': first_place_group,
                'second_place_group': second_place_group,
                'first_place_reason': first_place_reason,
                'second_place_reason': second_place_reason,
                'general_comment': general_comment,
                'show_evaluation_preview': True
            })
    
    # グループデータをJSONとして準備
    import json
    groups_data = []
    for group in groups:
        members_data = []
        for member in group.groupmember_set.all():
            members_data.append({
                'id': member.student.id,
                'name': member.student.full_name
            })
        
        groups_data.append({
            'id': group.id,
            'name': group.group_name or f'{group.group_number}グループ',
            'members': members_data
        })
    
    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'groups_json': json.dumps(groups_data),
        'is_closed': is_closed,
    }
    return render(request, 'school_management/improved_peer_evaluation_form.html', context)

def improved_peer_evaluation_form(request, token):
    """改善されたピア評価フォーム（学生用）"""
    try:
        import uuid
        evaluator_token = uuid.UUID(token)
        peer_evaluation = get_object_or_404(PeerEvaluation, evaluator_token=evaluator_token)
        lesson_session = peer_evaluation.lesson_session
        evaluator_group = peer_evaluation.evaluator_group
        
        # 他のグループ（評価対象）
        other_groups = Group.objects.filter(lesson_session=lesson_session).exclude(id=evaluator_group.id)
        
        # 自分のグループのメンバー（自分以外）
        group_members = GroupMember.objects.filter(group=evaluator_group)
        
        if request.method == 'POST':
            # 基本的なピア評価情報を更新
            first_place_id = request.POST.get('first_place_group')
            second_place_id = request.POST.get('second_place_group')
            first_place_reason = request.POST.get('first_place_reason', '')
            second_place_reason = request.POST.get('second_place_reason', '')
            general_comment = request.POST.get('general_comment', '')
            
            if first_place_id and second_place_id:
                peer_evaluation.first_place_group_id = first_place_id
                peer_evaluation.second_place_group_id = second_place_id
                peer_evaluation.first_place_reason = first_place_reason
                peer_evaluation.second_place_reason = second_place_reason
                peer_evaluation.general_comment = general_comment
                peer_evaluation.save()
                
                # 貢献度評価を保存
                for member in group_members:
                    contribution_score = request.POST.get(f'contribution_{member.id}')
                    if contribution_score:
                        ContributionEvaluation.objects.update_or_create(
                            peer_evaluation=peer_evaluation,
                            evaluatee=member.student,
                            defaults={'contribution_score': int(contribution_score)}
                        )
                
                messages.success(request, 'ピア評価を送信しました。ご協力ありがとうございました。')
                return render(request, 'school_management/peer_evaluation_thanks.html', {
                    'lesson_session': lesson_session,
                    'evaluator_group': evaluator_group
                })
            else:
                messages.error(request, '必須項目を入力してください。')
        
        context = {
            'lesson_session': lesson_session,
            'evaluator_group': evaluator_group,
            'other_groups': other_groups,
            'group_members': group_members,
            'peer_evaluation': peer_evaluation,
        }
        return render(request, 'school_management/improved_peer_evaluation_form.html', context)
        
    except (ValueError, PeerEvaluation.DoesNotExist):
        return render(request, 'school_management/peer_evaluation_error.html', {
            'error_message': '無効なアクセスです。正しいリンクからアクセスしてください。'
        })


def close_peer_evaluation(request, session_id):
    """ピア評価を締め切る"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if not request.user.role in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_closed = True
        lesson_session.save()
        
        from django.contrib import messages
        messages.success(request, 'ピア評価を締め切りました。')
    
    return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)


def reopen_peer_evaluation(request, session_id):
    """ピア評価を再開する"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if not request.user.role in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_closed = False
        lesson_session.save()
        
        from django.contrib import messages
        messages.success(request, 'ピア評価を再開しました。')
    
    return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)


def peer_evaluation_results(request, session_id):
    """ピア評価結果表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    # ピア評価データを取得
    evaluations = PeerEvaluation.objects.filter(lesson_session=lesson_session).select_related(
        'evaluator_group', 'first_place_group', 'second_place_group'
    )
    
    # グループ別集計
    groups = Group.objects.filter(lesson_session=lesson_session)
    group_stats = {}
    
    for group in groups:
        # このグループが1位に選ばれた回数
        first_place_votes = evaluations.filter(first_place_group=group).count()
        # このグループが2位に選ばれた回数
        second_place_votes = evaluations.filter(second_place_group=group).count()
        # このグループが評価した回数
        evaluations_given = evaluations.filter(evaluator_group=group).count()
        
        group_stats[group.id] = {
            'group': group,
            'first_place_votes': first_place_votes,
            'second_place_votes': second_place_votes,
            'total_votes': first_place_votes + second_place_votes,
            'evaluations_given': evaluations_given,
            'score': first_place_votes * 2 + second_place_votes  # 1位=2点、2位=1点でスコア計算
        }
    
    # スコア順でソート
    sorted_groups = sorted(group_stats.values(), key=lambda x: x['score'], reverse=True)
    
    context = {
        'lesson_session': lesson_session,
        'evaluations': evaluations,
        'group_stats': sorted_groups,
        'total_evaluations': evaluations.count(),
        'total_groups': groups.count(),
    }
    
    return render(request, 'school_management/peer_evaluation_results.html', context)

# 学生のポイント更新
@login_required
@csrf_exempt
@require_POST
def update_student_points(request, student_id):
    """学生のポイントを更新する（クラス独立型）

    JSON ボディで { "points": <数値>, "class_id": <クラスID> } を受け取る。
    class_id は必須で、クラス単位の `StudentClassPoints` のみを更新する。
    総合ポイント（CustomUser.points）は使用しない。
    """
    if request.method == 'POST' and request.headers.get('content-type') == 'application/json':
        try:
            import json
            data = json.loads(request.body)
            points = data.get('points', 0)

            student = get_object_or_404(CustomUser, id=student_id, role='student')
            class_id = data.get('class_id')

            if not class_id:
                return JsonResponse({'success': False, 'error': 'class_idが必須です'})

            # 担当教師のチェックを追加
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
            
            scp, created = StudentClassPoints.objects.get_or_create(
                student=student,
                classroom=classroom,
                defaults={'points': 0}
            )
            scp.points = int(points)
            scp.save()

            return JsonResponse({'success': True, 'message': 'ポイントが更新されました'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': '不正なリクエストです'})


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


# QRコード関連のビュー
@login_required
def qr_code_list(request):
    """QRコード管理 - クラス選択（教員用）"""
    if not request.user.is_teacher:
        messages.error(request, '教員のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    # 担当クラスを取得
    classrooms = ClassRoom.objects.filter(teachers=request.user).order_by('-year', '-semester', 'class_name')
    
    # 各クラスの学生数とポイント情報を取得
    class_data = []
    for classroom in classrooms:
        student_count = classroom.students.count()
        
        # このクラスの学生のQRコードスキャン数を集計
        students = classroom.students.all()
        total_scans = 0
        for student in students:
            qr_code = StudentQRCode.objects.filter(student=student).first()
            if qr_code:
                total_scans += qr_code.scans.count()
        
        class_data.append({
            'classroom': classroom,
            'student_count': student_count,
            'total_scans': total_scans,
        })
    
    context = {
        'classes': class_data,
    }
    return render(request, 'school_management/qr_code_list.html', context)


@login_required
def class_qr_codes(request, class_id):
    """クラス別QRコード表示"""
    if not request.user.is_teacher:
        messages.error(request, '教員のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    # クラスを取得
    classroom = get_object_or_404(ClassRoom, id=class_id)
    
    # 教員がこのクラスを担当しているかチェック
    if request.user not in classroom.teachers.all():
        messages.error(request, 'このクラスにアクセスする権限がありません。')
        return redirect('school_management:dashboard')
    
    # このクラスに在籍している学生のみを取得
    students = classroom.students.all()
    
    # 各学生のQRコード情報を取得
    qr_codes = []
    for student in students:
        qr_code, created = StudentQRCode.objects.get_or_create(
            student=student,
            defaults={'is_active': True}
        )
        scan_url = request.build_absolute_uri(
            reverse('school_management:qr_code_scan', kwargs={'qr_code_id': qr_code.qr_code_id})
        ) + f'?class_id={class_id}'
        
        # このクラスでのポイントを取得
        try:
            class_points_obj = StudentClassPoints.objects.get(student=student, classroom=classroom)
            class_points = class_points_obj.points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        qr_codes.append({
            'student': student,
            'qr_code': qr_code,
            'scan_count': qr_code.scans.count(),
            'qr_image': generate_qr_code_image(scan_url),
            'class_points': class_points  # クラスごとのポイントを追加
        })
    
    context = {
        'classroom': classroom,
        'qr_codes': qr_codes,
    }
    return render(request, 'school_management/class_qr_codes.html', context)


@login_required
def qr_code_detail(request, student_id):
    """学生のQRコード詳細表示"""
    if not request.user.is_teacher:
        messages.error(request, '教員のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    student = get_object_or_404(Student, id=student_id)
    
    # 担当クラスに所属しているかチェック
    student_classes = student.classroom_set.filter(teachers=request.user)
    if not student_classes.exists():
        messages.error(request, 'この学生のQRコードを表示する権限がありません。')
        return redirect('school_management:dashboard')
    
    qr_code, created = StudentQRCode.objects.get_or_create(
        student=student,
        defaults={'is_active': True}
    )
    
    # スキャン履歴を取得
    scans = qr_code.scans.select_related('scanned_by').order_by('-scanned_at')
    scan_url = request.build_absolute_uri(
        reverse('school_management:qr_code_scan', kwargs={'qr_code_id': qr_code.qr_code_id})
    )
    
    # クラスIDをGETパラメータから取得
    class_id = request.GET.get('class_id')
    classroom = None
    if class_id:
        try:
            classroom = ClassRoom.objects.get(id=class_id)
        except ClassRoom.DoesNotExist:
            pass
    
    context = {
        'student': student,
        'qr_code': qr_code,
        'scans': scans,
        'qr_image': generate_qr_code_image(scan_url),
        'total_points': scans.aggregate(total=models.Sum('points_awarded'))['total'] or 0,
        'classroom': classroom,
    }
    return render(request, 'school_management/qr_code_detail.html', context)


def qr_code_scan(request, qr_code_id):
    """QRコードスキャン処理（先生専用）"""
    try:
        qr_code = get_object_or_404(StudentQRCode, qr_code_id=qr_code_id, is_active=True)
        
        # ログインしていない場合はログインページにリダイレクト
        if not request.user.is_authenticated:
            messages.warning(request, 'QRコードをスキャンするにはログインが必要です。')
            return redirect('school_management:login')
        
        # 先生のみスキャン可能
        if not request.user.is_teacher:
            messages.error(request, 'QRコードのスキャンは先生のみ可能です。')
            return redirect('school_management:student_dashboard')
        
        # クラスIDをGETパラメータから取得
        class_id = request.GET.get('class_id')
        target_classroom = None
        if class_id:
            try:
                target_classroom = ClassRoom.objects.get(id=class_id, teachers=request.user)
            except ClassRoom.DoesNotExist:
                pass
        
        # 現在の授業セッションを取得（先生が担当する授業の中で今日の日付のもの）
        from datetime import date
        today = date.today()
        current_session = None
        
        # 先生が担当する授業セッションを取得
        if target_classroom:
            # 指定されたクラスの今日の授業セッション
            teacher_sessions = LessonSession.objects.filter(
                classroom=target_classroom,
                date=today
            ).order_by('-created_at')
        else:
            # すべての担当クラスから今日の授業セッション
            teacher_sessions = LessonSession.objects.filter(
                classroom__teachers=request.user,
                date=today
            ).order_by('-created_at')
        
        if teacher_sessions.exists():
            current_session = teacher_sessions.first()
        
        # スキャン処理
        scan = QRCodeScan.objects.create(
            qr_code=qr_code,
            scanned_by=request.user,
            lesson_session=current_session,
            points_awarded=1
        )
        
        # ポイントを更新（授業セッションがなくてもクラスが指定されていればポイント付与）
        update_classroom = current_session.classroom if current_session else target_classroom
        
        if update_classroom:
            # 授業セッションごとのポイント（セッションがある場合のみ）
            if current_session:
                student_lesson_points, created = StudentLessonPoints.objects.get_or_create(
                    student=qr_code.student,
                    lesson_session=current_session,
                    defaults={'points': 0}
                )
                student_lesson_points.points += 1
                student_lesson_points.save()

            # クラス累計ポイントを更新（必ず更新）
            try:
                scp, scp_created = StudentClassPoints.objects.get_or_create(
                    student=qr_code.student,
                    classroom=update_classroom,
                    defaults={'points': 0}
                )
                scp.points += 1
                scp.save()
            except Exception as e:
                # クラスポイント更新失敗をログに記録
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f'クラスポイント更新エラー: {str(e)}')
        
        # QRコードの最終使用日時を更新
        qr_code.last_used_at = timezone.now()
        qr_code.save()
        
        # スキャン成功ページを表示
        user_scan_count = QRCodeScan.objects.filter(scanned_by=request.user).count()
        
        # 学生のクラスポイントを取得（表示用）
        student_class_points = None
        if update_classroom:
            try:
                scp = StudentClassPoints.objects.get(student=qr_code.student, classroom=update_classroom)
                student_class_points = scp.points
            except StudentClassPoints.DoesNotExist:
                student_class_points = 0
        
        context = {
            'qr_code': qr_code,
            'lesson_session': current_session,
            'scan_time': timezone.now().strftime('%Y年%m月%d日 %H:%M'),
            'user_scan_count': user_scan_count,
            'classroom': update_classroom,
            'student_class_points': student_class_points,
            'points_added': True if update_classroom else False,
        }
        return render(request, 'school_management/qr_code_scan.html', context)
        
    except Exception as e:
        context = {
            'qr_code': None,
            'error_message': f'QRコードのスキャンに失敗しました: {str(e)}'
        }
        return render(request, 'school_management/qr_code_scan.html', context)


@login_required
def student_qr_code_view(request):
    """学生用QRコード表示"""
    if not request.user.is_student:
        messages.error(request, '学生のみアクセス可能です。')
        return redirect('school_management:dashboard')
    
    qr_code, created = StudentQRCode.objects.get_or_create(
        student=request.user,
        defaults={'is_active': True}
    )
    
    # スキャン履歴を取得
    scans = qr_code.scans.select_related('scanned_by').order_by('-scanned_at')
    
    context = {
        'qr_code': qr_code,
        'scans': scans,
        'qr_image': generate_qr_code_image(qr_code.qr_code_url),
        'total_points': scans.aggregate(total=models.Sum('points_awarded'))['total'] or 0,
    }
    return render(request, 'school_management/student_qr_code.html', context)


def generate_qr_code_image(url):
    """QRコード画像を生成"""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 画像をbase64エンコード
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        print(f"QRコード生成エラー: {e}")
        return None

@login_required
def class_evaluation_view(request, class_id):
    """クラスごとの評価一覧（写真のような形式）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all().order_by('student_number')
    
    # 授業回の一覧を取得
    sessions = LessonSession.objects.filter(classroom=classroom).order_by('session_number')
    
    # 各学生の評価データを取得
    student_evaluations = []
    
    for student in students:
        # 各授業回のデータ（ポイント + ピア評価スコア）
        session_data = {}
        session_count = 0
        total_qr_points = 0
        
        for session in sessions:
            session_key = f"第{session.session_number}回"
            
            # QRコードポイントを取得
            qr_points = 0
            lesson_point = StudentLessonPoints.objects.filter(
                lesson_session=session,
                student=student
            ).first()
            if lesson_point:
                qr_points = lesson_point.points
                session_count += 1
                total_qr_points += qr_points
            
            # 小テストスコアを取得
            quiz_score = 0
            has_quiz = False
            try:
                quiz = Quiz.objects.filter(lesson_session=session).first()
                if quiz:
                    has_quiz = True
                    quiz_score_obj = QuizScore.objects.filter(
                        quiz=quiz,
                        student=student,
                        is_cancelled=False
                    ).first()
                    if quiz_score_obj:
                        # 小テストのスコア（0-100点）をそのまま使用
                        quiz_score = quiz_score_obj.score
            except Exception as e:
                print(f"小テストスコア取得エラー: {e}")
                pass
            
            # ピア評価スコアを取得（1位=5点、2位=3点）
            peer_evaluation_score = 0
            try:
                # この学生が所属するグループを取得
                student_groups = Group.objects.filter(
                    lesson_session=session,
                    groupmember__student=student
                )
                
                if student_groups.exists() and session.has_peer_evaluation:
                    from .models import PeerEvaluation
                    # この学生のグループが1位に選ばれた回数
                    first_place_count = PeerEvaluation.objects.filter(
                        lesson_session=session,
                        first_place_group__in=student_groups
                    ).count()
                    
                    # この学生のグループが2位に選ばれた回数
                    second_place_count = PeerEvaluation.objects.filter(
                        lesson_session=session,
                        second_place_group__in=student_groups
                    ).count()
                    
                    # 1位×5点 + 2位×3点
                    peer_evaluation_score = first_place_count * 5 + second_place_count * 3
            except Exception as e:
                print(f"ピア評価スコア取得エラー: {e}")
                pass
            
            session_data[session_key] = {
                'qr_points': qr_points,
                'quiz_score': quiz_score,
                'peer_score': peer_evaluation_score,
                'total_score': qr_points + quiz_score + peer_evaluation_score,
                'date': session.date,
                'has_peer_evaluation': session.has_peer_evaluation,
                'has_quiz': has_quiz
            }
        
        # 出席率と平均ポイントを計算
        total_sessions = sessions.count()
        # データベースから保存された出席率、出席点、ポイントを取得
        saved_multiplied_points = 0
        attendance_rate = 0
        saved_attendance_points = 0
        try:
            student_class_points = StudentClassPoints.objects.get(student=student, classroom=classroom)
            attendance_rate = student_class_points.attendance_rate
            saved_multiplied_points = student_class_points.points
            saved_attendance_points = student_class_points.attendance_points
        except StudentClassPoints.DoesNotExist:
            # 保存されていない場合は自動計算
            attendance_rate = (session_count / total_sessions * 100) if total_sessions > 0 else 0
        
        # 各種スコアの合計を計算
        total_peer_score = sum(data['peer_score'] for data in session_data.values())
        total_quiz_score = sum(data.get('quiz_score', 0) for data in session_data.values())
        total_combined_score = sum(data['total_score'] for data in session_data.values())
        
        # 保存されたポイントがある場合はそれを使う、なければ新規計算
        if saved_multiplied_points > 0:
            multiplied_points = saved_multiplied_points
        else:
            # 点数（合計スコア × 倍率）
            multiplied_points = total_combined_score * 2  # 倍率2倍
        
        # クラスポイントは保存されている値、なければ計算値
        class_points_display = saved_multiplied_points if saved_multiplied_points > 0 else multiplied_points
        
        average_points = round(total_qr_points / session_count, 1) if session_count > 0 else 0
        
        # 出席点を使用（保存されたものがあればそれを使う）
        attendance_points_value = saved_attendance_points if saved_attendance_points > 0 else 0
        
        # 合計点は出席点 + クラスポイント × 2
        total_points_calculated = attendance_points_value + (class_points_display * 2)
        
        student_evaluations.append({
            'student': student,
            'total_points': total_points_calculated,  # 合計点は出席点 + 点数
            'total_peer_score': total_peer_score,
            'total_quiz_score': total_quiz_score,  # 小テストスコアの合計
            'total_combined_score': total_combined_score,
            'attendance_points': attendance_points_value,  # 出席点（保存された値または0）
            'attendance_rate': attendance_rate,
            'multiplied_points': multiplied_points,  # 倍率2倍
            'multiplier': 2,
            'session_data': session_data,
            'session_count': session_count,
            'average_points': average_points,
            'class_points': class_points_display,  # クラスのポイント（保存されている値または計算値）
            'student_points': student.points,  # 学生の全体ポイント
            'qr_points': total_qr_points,  # クラスのQRコードポイントの合計
        })
    
    session_list = [f"第{session.session_number}回" for session in sessions]
    
    # 各授業回のピア評価平均値を計算
    session_peer_averages = {}
    for session in sessions:
        if session.has_peer_evaluation:
            from .models import ContributionEvaluation
            peer_scores = ContributionEvaluation.objects.filter(
                peer_evaluation__lesson_session=session
            ).aggregate(avg_score=models.Avg('contribution_score'))
            
            avg_score = round(peer_scores['avg_score'] or 0, 1)
            session_peer_averages[session.id] = avg_score
            print(f"Session {session.session_number}: PE average = {avg_score}")
        else:
            session_peer_averages[session.id] = None
            print(f"Session {session.session_number}: No peer evaluation")
    
    print(f"Session peer averages: {session_peer_averages}")
    
    context = {
        'classroom': classroom,
        'student_evaluations': student_evaluations,
        'session_list': session_list,
        'sessions': sessions,  # 日付情報も渡す
        'session_peer_averages': session_peer_averages,  # ピア評価平均値
        'total_sessions': len(session_list),
    }
    return render(request, 'school_management/class_evaluation.html', context)

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
    total_points = data.get('total_points', 0)
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
        defaults={'points': total_points, 'attendance_rate': attendance_rate, 'attendance_points': attendance_points}
    )
    
    if not created:
        # 既存のレコードのpoints、出席率、出席点を更新
        student_class_points.points = total_points
        student_class_points.attendance_rate = attendance_rate
        student_class_points.attendance_points = attendance_points
        student_class_points.save()
    
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
