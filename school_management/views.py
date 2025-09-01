from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.middleware.csrf import get_token
from django.db.models import Avg, Count, Q, Max
from django.db import models
# import qrcode  # 一時的にコメントアウト
# import io
# import base64
from .models import ClassRoom, Student, Teacher, LessonSession, Quiz, QuizScore, PeerEvaluation, Attendance, Group, GroupMember, ContributionEvaluation, CustomUser

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
            if user.is_teacher:
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
        return admin_dashboard(request)
    elif request.user.is_teacher:
        return teacher_dashboard(request)
    elif request.user.is_student:
        return student_dashboard(request)
    else:
        return redirect('school_management:login')


@login_required
def admin_dashboard(request):
    """管理者ダッシュボード"""
    if request.user.role != 'admin':
        messages.error(request, '管理者権限が必要です。')
        return redirect('school_management:dashboard')
    
    # 統計情報を取得
    total_teachers = CustomUser.objects.filter(role='teacher').count()
    total_students = CustomUser.objects.filter(role='student').count()
    total_classes = ClassRoom.objects.count()
    total_admins = CustomUser.objects.filter(role='admin').count()
    
    # 全ユーザー情報
    all_teachers = CustomUser.objects.filter(role='teacher').order_by('-date_joined')
    all_students = CustomUser.objects.filter(role='student').order_by('-date_joined')
    all_admins = CustomUser.objects.filter(role='admin').order_by('-date_joined')
    
    # 最近追加された教員（最新5名）
    recent_teachers = all_teachers[:5]
    
    # 最近追加された学生（最新10名）
    recent_students = all_students[:10]
    
    # 最近作成されたクラス（最新5個）
    recent_classes = ClassRoom.objects.order_by('-created_at')[:5]
    
    context = {
        'user': request.user,
        'total_teachers': total_teachers,
        'total_students': total_students,
        'total_classes': total_classes,
        'total_admins': total_admins,
        'all_teachers': all_teachers,
        'all_students': all_students,
        'all_admins': all_admins,
        'recent_teachers': recent_teachers,
        'recent_students': recent_students,
        'recent_classes': recent_classes,
    }
    
    return render(request, 'school_management/admin_dashboard.html', context)


@login_required
def teacher_list_view(request):
    """教員一覧（管理者専用）"""
    if request.user.role != 'admin':
        messages.error(request, '管理者権限が必要です。')
        return redirect('school_management:dashboard')
    
    teachers = CustomUser.objects.filter(role='teacher').order_by('full_name')
    
    context = {
        'teachers': teachers,
    }
    return render(request, 'school_management/teacher_list.html', context)


@login_required
def teacher_create_view(request):
    """教員作成（管理者専用）"""
    if request.user.role != 'admin':
        messages.error(request, '管理者権限が必要です。')
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        try:
            # フォームデータを取得
            teacher_id = request.POST.get('teacher_id')
            full_name = request.POST.get('full_name')
            email = request.POST.get('email')
            password = request.POST.get('password')
            
            # バリデーション
            if not all([email, full_name, password]):
                messages.error(request, 'メールアドレス、氏名、パスワードは必須です。')
                return render(request, 'school_management/teacher_create.html')
            
            # メールアドレスの重複チェック
            if CustomUser.objects.filter(email=email).exists():
                messages.error(request, 'このメールアドレスは既に使用されています。')
                return render(request, 'school_management/teacher_create.html')
            
            # 教員IDの重複チェック（入力されている場合）
            if teacher_id and CustomUser.objects.filter(teacher_id=teacher_id).exists():
                messages.error(request, 'この教員IDは既に使用されています。')
                return render(request, 'school_management/teacher_create.html')
            
            # 教員を作成（CustomUserManagerのcreate_userを使用）
            teacher = CustomUser.objects.create_user(
                email=email,
                full_name=full_name,
                password=password,
                role='teacher',
                teacher_id=teacher_id or ''
            )
            
            messages.success(request, f'教員「{teacher.full_name}」を追加しました。')
            return redirect('school_management:teacher_list')
            
        except Exception as e:
            messages.error(request, f'教員の作成に失敗しました: {str(e)}')
            return render(request, 'school_management/teacher_create.html')
    
    return render(request, 'school_management/teacher_create.html')


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
    
    context = {
        'student_classrooms': student_classrooms,
        'recent_sessions': recent_sessions,
        'pending_evaluations': pending_evaluations,
        'total_classes': student_classrooms.count(),
    }
    return render(request, 'school_management/student_dashboard.html', context)

# クラス管理ビュー
@login_required
def class_list_view(request):
    """クラス一覧"""
    # 管理者の場合は全てのクラスを表示
    if request.user.role == 'admin':
        classes = ClassRoom.objects.all()
    else:
        # 教員の場合は担当クラスのみ表示
        classes = ClassRoom.objects.filter(teachers=request.user)
    return render(request, 'school_management/class_list.html', {'classes': classes})

@login_required
def class_detail_view(request, class_id):
    """クラス詳細"""
    # 管理者の場合は全てのクラスにアクセス可能
    if request.user.role == 'admin':
        classroom = get_object_or_404(ClassRoom, id=class_id)
    else:
        # 教員の場合は担当クラスのみアクセス可能
        classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    students = classroom.students.all()
    lessons = LessonSession.objects.filter(classroom=classroom).order_by('-date')[:5]  # 最近の5件
    sessions = LessonSession.objects.filter(classroom=classroom)  # 全ての授業回（カウント用）
    peer_evaluations = PeerEvaluation.objects.filter(lesson_session__classroom=classroom)
    
    context = {
        'classroom': classroom,
        'students': students,
        'lessons': lessons,
        'sessions': sessions,  # 授業回数表示用
        'peer_evaluations': peer_evaluations,
        'recent_lessons': lessons,
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
@login_required
def student_list_view(request):
    """学生一覧"""
    # 役割が学生で、student_numberが設定されているユーザーのみ表示
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
    
    # 所属クラス一覧
    classes = student.classroom_set.all()
    
    context = {
        'student': student,
        'classes': classes,
    }
    return render(request, 'school_management/student_detail.html', context)

@login_required
def class_student_detail_view(request, class_id, student_number):
    """クラス内の学生詳細"""
    # 管理者の場合は全てのクラスにアクセス可能
    if request.user.role == 'admin':
        classroom = get_object_or_404(ClassRoom, id=class_id)
    else:
        # 教員の場合は担当クラスのみアクセス可能
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
                    errors.append(f'行{line_num}: 必要な項目が不足しています - {line}')
                    error_count += 1
                    continue
                
                student_number = parts[0]
                full_name = parts[1]
                furigana = parts[2]
                email = parts[3] if len(parts) > 3 else ''
                
                try:
                    # 重複チェック
                    if Student.objects.filter(student_number=student_number).exists():
                        errors.append(f'行{line_num}: 学生番号が既に存在します - {student_number}')
                        error_count += 1
                        continue
                    
                    if email and Student.objects.filter(email=email).exists():
                        errors.append(f'行{line_num}: メールアドレスが既に存在します - {email}')
                        error_count += 1
                        continue
                    
                    # 学生作成
                    Student.objects.create(
                        student_number=student_number,
                        full_name=full_name,
                        furigana=furigana,
                        email=email or ''
                    )
                    added_count += 1
                    
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
                # 学籍番号の重複チェック
                if Student.objects.filter(student_number=student_number).exists():
                    messages.error(request, f'学籍番号 "{student_number}" は既に登録されています。別の学籍番号を入力してください。')
                else:
                    try:
                        Student.objects.create(
                            student_number=student_number,
                            full_name=full_name,
                            furigana=furigana,
                            email=email or ''
                        )
                        messages.success(request, '学生を追加しました。')
                        return redirect('school_management:student_list')
                    except Exception as e:
                        messages.error(request, f'学生の追加中にエラーが発生しました: {str(e)}')
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
            email = parts[2].strip() if len(parts) > 2 else f'{student_number}@example.com'
            
            try:
                # 重複チェック（学籍番号またはメールアドレス）
                if Student.objects.filter(student_number=student_number).exists():
                    errors.append(f'行{line_num}: 学生番号が既に存在します - {student_number}')
                    error_count += 1
                    continue
                    
                if Student.objects.filter(email=email).exists():
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
        return redirect('school_management:group_management', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
        'students': students,
        'groups': groups,
    }
    return render(request, 'school_management/group_management.html', context)


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
    """学生のポイントを更新する"""
    if request.method == 'POST' and request.headers.get('content-type') == 'application/json':
        try:
            import json
            data = json.loads(request.body)
            points = data.get('points', 0)
            
            student = get_object_or_404(CustomUser, id=student_id, role='student')
            student.points = int(points)
            student.save()
            
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
            classroom = get_object_or_404(ClassRoom, id=class_id)
            
            # 学生をクラスから削除
            classroom.students.remove(student)
            
            return JsonResponse({'success': True, 'message': f'{student.full_name}さんをクラスから除籍しました'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': '不正なリクエストです'})
