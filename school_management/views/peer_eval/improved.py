import uuid
import json
import secrets
from datetime import timedelta
from urllib import parse, request as urllib_request, error as urllib_error
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from ...models import (
    LessonSession,
    Group,
    GroupMember,
    PeerEvaluation,
    ContributionEvaluation,
    Student,
    GoogleOAuthSession,
)


def _normalize_email(value):
    return (value or '').strip().lower()


def _is_allowed_domain(email):
    email = _normalize_email(email)
    if '@' not in email:
        return False
    domain = email.rsplit('@', 1)[1]
    return bool(settings.ALLOWED_GMAIL_DOMAINS) and domain in settings.ALLOWED_GMAIL_DOMAINS


def _google_config_ready():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def _load_verified_oauth_session(request, lesson_session):
    session_id = request.COOKIES.get(settings.PEER_EVAL_SESSION_COOKIE_NAME)
    if not session_id:
        return None, None

    oauth_session = GoogleOAuthSession.objects.filter(
        session_id=session_id,
        expires_at__gt=timezone.now(),
    ).first()
    if not oauth_session:
        return None, None

    email = _normalize_email(oauth_session.email)
    if not _is_allowed_domain(email):
        oauth_session.delete()
        return None, None

    student = lesson_session.classroom.students.filter(email__iexact=email).first()
    if not student or student.role != 'student':
        return None, None

    return oauth_session, student


def _build_google_oauth_url(request, state):
    callback_url = request.build_absolute_uri(
        reverse('school_management:peer_evaluation_google_callback')
    )
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': callback_url,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
        'state': state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{parse.urlencode(params)}"


def _exchange_code_for_email(request, code):
    callback_url = request.build_absolute_uri(
        reverse('school_management:peer_evaluation_google_callback')
    )
    payload = parse.urlencode({
        'code': code,
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
        'redirect_uri': callback_url,
        'grant_type': 'authorization_code',
    }).encode('utf-8')

    token_request = urllib_request.Request(
        'https://oauth2.googleapis.com/token',
        data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )

    try:
        with urllib_request.urlopen(token_request, timeout=10) as response:
            token_data = json.loads(response.read().decode('utf-8'))
    except (urllib_error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    id_token = token_data.get('id_token')
    if not id_token:
        return None

    try:
        tokeninfo_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={parse.quote(id_token)}"
        with urllib_request.urlopen(tokeninfo_url, timeout=10) as response:
            token_info = json.loads(response.read().decode('utf-8'))
    except (urllib_error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    email = _normalize_email(token_info.get('email'))
    email_verified = str(token_info.get('email_verified', '')).lower() == 'true'
    audience = token_info.get('aud')

    if not email or not email_verified or audience != settings.GOOGLE_OAUTH_CLIENT_ID:
        return None

    return email

# ---------------------------------------------------------
# 作成・リンク管理
# ---------------------------------------------------------

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
            token = str(uuid.uuid4())
            PeerEvaluation.objects.create(
                lesson_session=lesson_session,
                evaluator_token=token,
                evaluator_group=group,
                first_place_group=groups.first(), # 仮の値（後でフォームで更新）
                second_place_group=groups.first() # 仮の値
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

# ---------------------------------------------------------
# 回答フォーム（学生用・共通）
# ---------------------------------------------------------

def peer_evaluation_common_form(request, session_id):
    """共通ピア評価フォーム"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student')
    is_closed = lesson_session.peer_evaluation_closed
    oauth_session, student = _load_verified_oauth_session(request, lesson_session)

    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'is_closed': is_closed,
        'requires_google_auth': False,
    }

    if not settings.ALLOWED_GMAIL_DOMAINS:
        context['requires_google_auth'] = True
        context['auth_error'] = 'ALLOWED_GMAIL_DOMAINS が未設定のため、このフォームは利用できません。'
        return render(request, 'school_management/improved_peer_evaluation_form.html', context)

    if not _google_config_ready():
        context['requires_google_auth'] = True
        context['auth_error'] = 'Google認証設定が未設定です。教員に連絡してください。'
        return render(request, 'school_management/improved_peer_evaluation_form.html', context)

    if not student:
        context['requires_google_auth'] = True
        context['google_auth_url'] = reverse('school_management:peer_evaluation_google_start', kwargs={'session_id': lesson_session.id})
        return render(request, 'school_management/improved_peer_evaluation_form.html', context)

    memberships = GroupMember.objects.filter(
        group__lesson_session=lesson_session,
        student=student,
    ).select_related('group')
    if memberships.count() != 1:
        context.update({
            'authenticated_student': student,
            'group_resolution_error': True,
            'auth_error': 'あなたの所属グループを特定できませんでした。担当教員に連絡してください。',
        })
        return render(request, 'school_management/improved_peer_evaluation_form.html', context)

    evaluator_group = memberships.first().group
    evaluator_group_member_names = list(
        GroupMember.objects.filter(group=evaluator_group)
        .exclude(student=student)
        .select_related('student')
        .values_list('student__full_name', flat=True)
    )

    existing_submission = PeerEvaluation.objects.filter(
        lesson_session=lesson_session,
        student=student,
    ).first()
    if existing_submission:
        context.update({
            'submission_exists': True,
            'submission': existing_submission,
            'authenticated_student': student,
            'evaluator_group': evaluator_group,
            'evaluator_group_member_names': evaluator_group_member_names,
        })
        return render(request, 'school_management/improved_peer_evaluation_form.html', context)
    
    if request.method == 'POST' and not is_closed:
        try:
            participant_count = int(request.POST.get('participant_count', 0))
        except (TypeError, ValueError):
            participant_count = 0
        first_place_id = request.POST.get('first_place_group')
        second_place_id = request.POST.get('second_place_group')
        
        if first_place_id and second_place_id:
            first_place = get_object_or_404(Group, id=first_place_id)
            second_place = get_object_or_404(Group, id=second_place_id)
            
            try:
                peer_evaluation = PeerEvaluation.objects.create(
                    lesson_session=lesson_session,
                    student=student,
                    email=_normalize_email(oauth_session.email),
                    evaluator_token=str(uuid.uuid4()),
                    evaluator_group=evaluator_group,
                    first_place_group=first_place,
                    second_place_group=second_place,
                    first_place_reason=request.POST.get('first_place_reason', ''),
                    second_place_reason=request.POST.get('second_place_reason', ''),
                    general_comment=request.POST.get('general_comment', '')
                )
            except IntegrityError:
                messages.error(request, 'この授業回のピア評価はすでに提出済みです。再提出はできません。')
                context.update({
                    'submission_exists': True,
                    'authenticated_student': student,
                    'evaluator_group': evaluator_group,
                    'evaluator_group_member_names': evaluator_group_member_names,
                })
                return render(request, 'school_management/improved_peer_evaluation_form.html', context)

            valid_member_ids = set(
                GroupMember.objects.filter(group=evaluator_group).values_list('student_id', flat=True)
            )
            valid_member_ids.discard(student.id)
            
            # 貢献度評価の保存
            if participant_count > 1:
                # 自分以外の人数分ループ (participant_count - 1)
                evaluation_count = participant_count - 1
                for i in range(evaluation_count):
                    member_id = request.POST.get(f'participant_{i}_member')
                    score = request.POST.get(f'participant_{i}_contribution')
                    
                    if member_id and score:
                        try:
                            member_id_int = int(member_id)
                            if member_id_int not in valid_member_ids:
                                continue
                            evaluatee = Student.objects.get(id=member_id_int)
                            ContributionEvaluation.objects.create(
                                peer_evaluation=peer_evaluation,
                                evaluatee=evaluatee,
                                contribution_score=int(score)
                            )
                        except (Student.DoesNotExist, ValueError):
                            pass
            
            return render(request, 'school_management/peer_evaluation_thanks.html', {
                'lesson_session': lesson_session,
                'first_place_group': first_place,
                'second_place_group': second_place,
                'show_evaluation_preview': True
            })

    # JSONデータ準備
    groups_data = []
    for group in groups:
        members_data = [{'id': m.student.id, 'name': m.student.full_name} for m in group.groupmember_set.all()]
        groups_data.append({
            'id': group.id, 
            'name': group.group_name or f'{group.group_number}グループ', 
            'members': members_data
        })
    
    context.update({
        'groups_json': json.dumps(groups_data),
        'authenticated_student': student,
        'evaluator_group': evaluator_group,
        'evaluator_group_member_names': evaluator_group_member_names,
    })
    return render(request, 'school_management/improved_peer_evaluation_form.html', context)


def peer_evaluation_google_start(request, session_id):
    """Google OAuth認証開始"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)

    if not settings.ALLOWED_GMAIL_DOMAINS:
        messages.error(request, 'ALLOWED_GMAIL_DOMAINS が未設定のため、認証を開始できません。')
        return redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)
    if not _google_config_ready():
        messages.error(request, 'Google認証設定が未設定のため、認証を開始できません。')
        return redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)

    state = signing.dumps({
        'session_id': lesson_session.id,
        'nonce': secrets.token_urlsafe(16),
    })
    response = redirect(_build_google_oauth_url(request, state))
    response.set_cookie(
        'peer_eval_oauth_state',
        state,
        max_age=600,
        secure=request.is_secure(),
        httponly=True,
        samesite='Lax',
    )
    return response


def peer_evaluation_google_callback(request):
    """Google OAuthコールバック"""
    expected_state = request.COOKIES.get('peer_eval_oauth_state')
    returned_state = request.GET.get('state')

    if not expected_state or expected_state != returned_state:
        messages.error(request, '認証状態が不正です。再ログインしてください。')
        response = redirect('school_management:login')
        response.delete_cookie('peer_eval_oauth_state')
        return response

    try:
        state_data = signing.loads(returned_state, max_age=600)
        session_id = int(state_data.get('session_id'))
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        messages.error(request, '認証状態が無効です。再ログインしてください。')
        response = redirect('school_management:login')
        response.delete_cookie('peer_eval_oauth_state')
        return response

    lesson_session = get_object_or_404(LessonSession, id=session_id)

    if request.GET.get('error'):
        messages.error(request, 'Google認証が完了しませんでした。再ログインしてください。')
        response = redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)
        response.delete_cookie('peer_eval_oauth_state')
        return response

    code = request.GET.get('code')
    email = _exchange_code_for_email(request, code) if code else None
    if not email:
        messages.error(request, 'メールアドレスの取得に失敗しました。再ログインしてください。')
        response = redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)
        response.delete_cookie('peer_eval_oauth_state')
        return response

    if not _is_allowed_domain(email):
        messages.error(request, '許可されていないメールドメインです。再ログインしてください。')
        response = redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)
        response.delete_cookie('peer_eval_oauth_state')
        return response

    student = lesson_session.classroom.students.filter(email__iexact=email).first()
    if not student or student.role != 'student':
        messages.error(request, 'この授業回の履修者として確認できませんでした。')
        response = redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)
        response.delete_cookie('peer_eval_oauth_state')
        return response

    oauth_session = GoogleOAuthSession.objects.create(
        session_id=secrets.token_urlsafe(32),
        email=_normalize_email(email),
        expires_at=timezone.now() + timedelta(hours=settings.PEER_EVAL_SESSION_TTL_HOURS),
    )

    if PeerEvaluation.objects.filter(lesson_session=lesson_session, student=student).exists():
        messages.error(request, 'この授業回のピア評価はすでに提出済みです。再提出はできません。')

    response = redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)
    response.delete_cookie('peer_eval_oauth_state')
    response.set_cookie(
        settings.PEER_EVAL_SESSION_COOKIE_NAME,
        oauth_session.session_id,
        max_age=settings.PEER_EVAL_SESSION_TTL_HOURS * 60 * 60,
        secure=request.is_secure(),
        httponly=True,
        samesite='Lax',
    )
    return response

def improved_peer_evaluation_form(request, token):
    """改善されたピア評価フォーム（学生用・個別トークン）"""
    try:
        evaluator_token = uuid.UUID(token)
        peer_evaluation = get_object_or_404(PeerEvaluation, evaluator_token=evaluator_token)
        lesson_session = peer_evaluation.lesson_session
        evaluator_group = peer_evaluation.evaluator_group
        other_groups = Group.objects.filter(lesson_session=lesson_session).exclude(id=evaluator_group.id)
        group_members = GroupMember.objects.filter(group=evaluator_group)
        
        if request.method == 'POST':
            first_place_id = request.POST.get('first_place_group')
            second_place_id = request.POST.get('second_place_group')
            
            if first_place_id and second_place_id:
                peer_evaluation.first_place_group_id = first_place_id
                peer_evaluation.second_place_group_id = second_place_id
                peer_evaluation.first_place_reason = request.POST.get('first_place_reason', '')
                peer_evaluation.second_place_reason = request.POST.get('second_place_reason', '')
                peer_evaluation.general_comment = request.POST.get('general_comment', '')
                peer_evaluation.save()
                
                # 貢献度評価
                for member in group_members:
                    score = request.POST.get(f'contribution_{member.id}')
                    if score:
                        ContributionEvaluation.objects.update_or_create(
                            peer_evaluation=peer_evaluation,
                            evaluatee=member.student,
                            defaults={'contribution_score': int(score)}
                        )
                
                messages.success(request, 'ピア評価を送信しました。')
                return render(request, 'school_management/peer_evaluation_thanks.html', {'lesson_session': lesson_session})
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
        return render(request, 'school_management/peer_evaluation_error.html', {'error_message': '無効なリンクです。'})

# ---------------------------------------------------------
# 管理・集計（先生用）
# ---------------------------------------------------------

@login_required
def close_peer_evaluation(request, session_id):
    """ピア評価を締め切る"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_closed = True
        lesson_session.save()
        messages.success(request, 'ピア評価を締め切りました。')
    
    return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)

@login_required
def reopen_peer_evaluation(request, session_id):
    """ピア評価を再開する"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_closed = False
        lesson_session.save()
        messages.success(request, 'ピア評価を再開しました。')
    
    return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)

@login_required
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
        first_place_votes = evaluations.filter(
            Q(first_place_group=group) | 
            Q(first_place_group_number=group.group_number)
        ).distinct().count()
        
        second_place_votes = evaluations.filter(
            Q(second_place_group=group) | 
            Q(second_place_group_number=group.group_number)
        ).distinct().count()
        
        evaluations_given = evaluations.filter(
            Q(evaluator_group=group) |
            Q(evaluator_group_number=group.group_number)
        ).distinct().count()
        
        group_stats[group.id] = {
            'group': group,
            'first_place_votes': first_place_votes,
            'second_place_votes': second_place_votes,
            'total_votes': first_place_votes + second_place_votes,
            'evaluations_given': evaluations_given,
            'score': first_place_votes * 2 + second_place_votes  # 1位=2点、2位=1点
        }
    
    sorted_groups = sorted(group_stats.values(), key=lambda x: x['score'], reverse=True)

    enrolled_students = lesson_session.classroom.students.filter(role='student').order_by('full_name')
    student_rows = []
    submitted_count = 0
    for enrolled_student in enrolled_students:
        submission = evaluations.filter(student=enrolled_student).order_by('-created_at').first()
        is_submitted = submission is not None
        if is_submitted:
            submitted_count += 1
        student_rows.append({
            'student': enrolled_student,
            'email': enrolled_student.email,
            'submitted': is_submitted,
            'submitted_at': submission.created_at if submission else None,
        })

    total_students = enrolled_students.count()
    submission_rate = round((submitted_count / total_students) * 100, 1) if total_students else 0
    
    context = {
        'lesson_session': lesson_session,
        'evaluations': evaluations,
        'group_stats': sorted_groups,
        'total_evaluations': evaluations.count(),
        'total_groups': groups.count(),
        'submission_rows': student_rows,
        'submitted_count': submitted_count,
        'total_students': total_students,
        'submission_rate': submission_rate,
    }
    
    return render(request, 'school_management/peer_evaluation_results.html', context)

@login_required
def delete_all_peer_evaluations(request, session_id):
    """ピア評価データを全て削除"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        messages.error(request, '権限がありません。')
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        # ピア評価データを削除（紐づく貢献度評価も自動削除され、ポイントも再計算されます）
        count = PeerEvaluation.objects.filter(lesson_session=lesson_session).count()
        PeerEvaluation.objects.filter(lesson_session=lesson_session).delete()
        
        messages.success(request, f'{count}件のピア評価データを削除し、リセットしました。')
        
    return redirect('school_management:peer_evaluation_results', session_id=session_id)
