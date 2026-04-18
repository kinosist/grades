import json
import secrets
import uuid
from datetime import timedelta
from urllib import parse, request as urllib_request, error as urllib_error

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import IntegrityError
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from ...models import (
    LessonSession,
    Group,
    GroupMember,
    PeerEvaluation,
    PeerEvaluationSettings,
    ContributionEvaluation,
    Student,
    StudentClassPoints,
    GoogleOAuthSession,
)


def _normalize_email(value):
    return (value or '').strip().lower()


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_submission_detail(evaluation, group_name_map, student_name_map):
    response = evaluation.response_json or {}
    group_evaluations = []
    for entry in response.get('other_group_eval', []):
        group_id = _safe_int(entry.get('group_id'))
        group_evaluations.append({
            'rank': entry.get('rank'),
            'target_name': group_name_map.get(group_id, f'グループID:{group_id}' if group_id else '不明'),
            'reason': (entry.get('reason') or '').strip(),
        })

    member_evaluations = []
    for entry in response.get('group_members_eval', []):
        member_id = _safe_int(entry.get('member_id'))
        member_evaluations.append({
            'rank': entry.get('rank'),
            'target_name': student_name_map.get(member_id, f'学生ID:{member_id}' if member_id else '不明'),
            'reason': (entry.get('reason') or '').strip(),
        })

    general_comment = (evaluation.general_comment or '').strip()
    class_comment = (evaluation.class_comment or '').strip()

    return {
        'group_evaluations': group_evaluations,
        'member_evaluations': member_evaluations,
        'general_comment': general_comment,
        'class_comment': class_comment,
        'has_content': bool(group_evaluations or member_evaluations or general_comment or class_comment),
    }


def _get_session_for_teacher_or_admin(request, session_id):
    if request.user.role == 'admin':
        return get_object_or_404(LessonSession, id=session_id)
    return get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)


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
    """ピア評価の受付開始（設定が存在する場合のみ）"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    groups = Group.objects.filter(lesson_session=lesson_session)
    
    if not groups.exists():
        messages.error(request, 'ピア評価を作成する前に、まずグループを設定してください。')
        return redirect('school_management:group_management', session_id=session_id)
    
    if not lesson_session.peer_evaluation_configured:
        messages.error(request, 'ピア評価設定を先に完了してください。')
        return redirect('school_management:peer_evaluation_settings', session_id=session_id)
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'start':
            if lesson_session.peer_evaluation_status == LessonSession.PeerEvaluationStatus.NOT_OPEN:
                lesson_session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.OPEN
                lesson_session.save()
                messages.success(request, 'ピア評価の受付を開始しました。')
        return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)
    
    # フォームURL生成
    form_url = request.build_absolute_uri(
        reverse('school_management:peer_evaluation_common', kwargs={'session_id': lesson_session.id})
    )
    
    evaluations = PeerEvaluation.objects.filter(lesson_session=lesson_session)
    
    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'students': lesson_session.classroom.students.filter(role='student'),
        'form_url': form_url,
        'evaluations': evaluations,
        'total_submissions': evaluations.count(),
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
    """ピア評価フォーム（PeerEvaluationSettings に基づいて動的に生成）"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # ピア評価設定が完了しているか確認
    if not lesson_session.peer_evaluation_configured:
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', {
            'lesson_session': lesson_session,
            'error_message': '教員がピア評価を設定していません。',
            'is_configuration_error': True,
        })
    
    pe_settings = lesson_session.peer_evaluation_settings
    
    # ステータスチェック
    if lesson_session.peer_evaluation_status == LessonSession.PeerEvaluationStatus.NOT_OPEN:
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', {
            'lesson_session': lesson_session,
            'error_message': 'ピア評価はまだ受付を開始していません。',
            'is_configuration_error': True,
        })
    
    if lesson_session.peer_evaluation_status == LessonSession.PeerEvaluationStatus.CLOSED:
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', {
            'lesson_session': lesson_session,
            'error_message': 'ピア評価の締切が過ぎています。提出はできません。',
            'is_closed': True,
        })
    
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student')
    oauth_session, student = _load_verified_oauth_session(request, lesson_session)

    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'requires_google_auth': False,
        'enable_comments': lesson_session.enable_comments,
        'enable_member_evaluation': pe_settings.enable_member_evaluation,
        'enable_group_evaluation': pe_settings.enable_group_evaluation,
        'enable_feedback': lesson_session.enable_feedback,
        'pe_settings': pe_settings,
    }

    if not settings.ALLOWED_GMAIL_DOMAINS:
        context['requires_google_auth'] = True
        context['auth_error'] = 'ALLOWED_GMAIL_DOMAINS が未設定です。教員に連絡してください。'
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)

    if not _google_config_ready():
        context['requires_google_auth'] = True
        context['auth_error'] = 'Google認証設定が未設定です。教員に連絡してください。'
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)

    if not student:
        context['requires_google_auth'] = True
        context['google_auth_url'] = reverse('school_management:peer_evaluation_google_start', kwargs={'session_id': lesson_session.id})
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)

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
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)

    evaluator_group = memberships.first().group
    evaluator_group_member_objects = list(
        GroupMember.objects.filter(group=evaluator_group)
        .exclude(student=student)
        .select_related('student')
        .values('student__id', 'student__full_name')
    )
    evaluator_group_member_names = [m['student__full_name'] for m in evaluator_group_member_objects]
    
    other_groups = groups.exclude(id=evaluator_group.id)
    ordered_other_groups = list(other_groups.order_by('group_number', 'id'))
    
    # 配点リストから順位数を取得
    member_score_list = pe_settings.member_scores or []
    group_score_list = pe_settings.group_scores or []
    
    max_member_rank = min(len(member_score_list), len(evaluator_group_member_objects))
    max_group_rank = min(len(group_score_list), len(ordered_other_groups))
    
    member_ranking_list = [
        {'rank': i + 1, 'points': member_score_list[i] if i < len(member_score_list) else 0}
        for i in range(max_member_rank)
    ]
    group_ranking_list = [
        {'rank': i + 1, 'points': group_score_list[i] if i < len(group_score_list) else 0}
        for i in range(max_group_rank)
    ]

    # 既存提出チェック
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
        })
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
    
    # POST処理
    if request.method == 'POST':
        if lesson_session.peer_evaluation_status == LessonSession.PeerEvaluationStatus.CLOSED:
            context.update({
                'authenticated_student': student,
                'evaluator_group': evaluator_group,
                'is_closed': True,
            })
            return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
        
        validation_errors = []
        response_json = {'group_members_eval': [], 'other_group_eval': []}
        
        # グループ評価バリデーション
        if pe_settings.enable_group_evaluation:
            selected_group_ids = set()
            for rank_item in group_ranking_list:
                rank = rank_item['rank']
                group_id = request.POST.get(f'group_rank_{rank}')
                reason = request.POST.get(f'group_reason_{rank}', '')
                
                if not group_id:
                    validation_errors.append(f'❌ グループ評価の{rank}位：グループを選択してください。')
                    continue
                
                if group_id in selected_group_ids:
                    validation_errors.append(f'❌ グループ評価：{rank}位に選ばれたグループは既に別の順位で選択されています。')
                    continue
                selected_group_ids.add(group_id)
                
                if pe_settings.group_reason_control == 'REQUIRED' and not reason.strip():
                    validation_errors.append(f'❌ グループ評価の{rank}位：理由を入力してください。')
                
                entry = {'rank': rank, 'group_id': int(group_id)}
                if pe_settings.group_reason_control != 'DISABLED':
                    entry['reason'] = reason
                response_json['other_group_eval'].append(entry)
        
        # メンバー評価バリデーション
        if pe_settings.enable_member_evaluation:
            selected_member_ids = set()
            for rank_item in member_ranking_list:
                rank = rank_item['rank']
                member_id = request.POST.get(f'member_rank_{rank}')
                reason = request.POST.get(f'member_reason_{rank}', '')
                
                if not member_id:
                    validation_errors.append(f'❌ チームメンバー評価の{rank}位：メンバーを選択してください。')
                    continue
                
                if member_id in selected_member_ids:
                    validation_errors.append(f'❌ チームメンバー評価：{rank}位に選ばれたメンバーは既に別の順位で選択されています。')
                    continue
                selected_member_ids.add(member_id)
                
                if pe_settings.member_reason_control == 'REQUIRED' and not reason.strip():
                    validation_errors.append(f'❌ チームメンバー評価の{rank}位：理由を入力してください。')
                
                entry = {'rank': rank, 'member_id': int(member_id)}
                if pe_settings.member_reason_control != 'DISABLED':
                    entry['reason'] = reason
                response_json['group_members_eval'].append(entry)
        
        if validation_errors:
            context.update({
                'authenticated_student': student,
                'evaluator_group': evaluator_group,
                'evaluator_group_member_names': evaluator_group_member_names,
                'evaluator_group_member_objects': evaluator_group_member_objects,
                'other_groups': ordered_other_groups,
                'member_ranking_list': member_ranking_list,
                'group_ranking_list': group_ranking_list,
                'max_member_rank': max_member_rank,
                'max_group_rank': max_group_rank,
                'show_scores': pe_settings.show_points,
                'validation_errors': validation_errors,
            })
            return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
        
        try:
            peer_evaluation = PeerEvaluation.objects.create(
                lesson_session=lesson_session,
                student=student,
                email=_normalize_email(oauth_session.email),
                evaluator_token=str(uuid.uuid4()),
                evaluator_group=evaluator_group,
                response_json=response_json,
                general_comment=request.POST.get('general_comment', ''),
                class_comment=request.POST.get('feedback', '') if lesson_session.enable_feedback else '',
            )
            
            # 直接付与モードの場合、ContributionEvaluationも作成
            if pe_settings.enable_member_evaluation and pe_settings.evaluation_method == 'DIRECT':
                for entry in response_json.get('group_members_eval', []):
                    rank = entry['rank']
                    member_id = entry['member_id']
                    score = member_score_list[rank - 1] if rank - 1 < len(member_score_list) else 0
                    try:
                        member = Student.objects.get(id=member_id, group_memberships__group=evaluator_group)
                        ContributionEvaluation.objects.create(
                            peer_evaluation=peer_evaluation,
                            evaluatee=member,
                            contribution_score=score
                        )
                    except (Student.DoesNotExist, ValueError):
                        pass
            
            messages.success(request, '評価を提出しました。ご協力ありがとうございます。')
            return render(request, 'school_management/peer_evaluation_thanks.html', {
                'lesson_session': lesson_session,
            })
        except IntegrityError:
            messages.error(request, 'この授業回のピア評価はすでに提出済みです。再提出はできません。')
            context.update({
                'submission_exists': True,
                'authenticated_student': student,
                'evaluator_group': evaluator_group,
            })
            return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
    
    context.update({
        'authenticated_student': student,
        'evaluator_group': evaluator_group,
        'evaluator_group_member_names': evaluator_group_member_names,
        'evaluator_group_member_objects': evaluator_group_member_objects,
        'other_groups': ordered_other_groups,
        'member_ranking_list': member_ranking_list,
        'group_ranking_list': group_ranking_list,
        'max_member_rank': max_member_rank,
        'max_group_rank': max_group_rank,
        'show_scores': pe_settings.show_points,
    })
    return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)


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

    normalized_email = _normalize_email(email)
    GoogleOAuthSession.objects.filter(email=normalized_email).delete()
    oauth_session = GoogleOAuthSession.objects.create(
        session_id=secrets.token_urlsafe(32),
        email=normalized_email,
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
    """改善されたピア評価フォーム（学生用・個別トークン）- レガシー互換"""
    try:
        evaluator_token = uuid.UUID(token)
        peer_evaluation = get_object_or_404(PeerEvaluation, evaluator_token=evaluator_token)
        lesson_session = peer_evaluation.lesson_session
        
        # 共通フォームにリダイレクト
        return redirect('school_management:peer_evaluation_common', session_id=lesson_session.id)
        
    except (ValueError, PeerEvaluation.DoesNotExist):
        return render(request, 'school_management/peer_evaluation_error.html', {'error_message': '無効なリンクです。'})

# ---------------------------------------------------------
# 管理・集計（先生用）
# ---------------------------------------------------------

@login_required
def close_peer_evaluation(request, session_id):
    """ピア評価を締め切る（集計して付与モードの場合は集計も実行）"""
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    lesson_session = _get_session_for_teacher_or_admin(request, session_id)
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        lesson_session.save()
        
        # 集計して付与モードの場合、締め切り時に集計を実行
        if lesson_session.peer_evaluation_configured:
            pe_settings = lesson_session.peer_evaluation_settings
            if pe_settings.enable_member_evaluation and pe_settings.evaluation_method == 'AGGREGATE':
                _aggregate_member_scores(lesson_session, pe_settings)

        # 締切時点の条件で全学生のクラスポイントを再計算
        for scp in StudentClassPoints.objects.filter(classroom=lesson_session.classroom).select_related('student'):
            scp.recalculate_total()
        
        messages.success(request, 'ピア評価を締め切りました。')
    
    return redirect('school_management:peer_evaluation_results', session_id=session_id)

@login_required
def reopen_peer_evaluation(request, session_id):
    """ピア評価を再開する"""
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    lesson_session = _get_session_for_teacher_or_admin(request, session_id)
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.OPEN
        lesson_session.save()
        for scp in StudentClassPoints.objects.filter(classroom=lesson_session.classroom).select_related('student'):
            scp.recalculate_total()
        messages.success(request, 'ピア評価を再開しました。')
    
    return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)


def _aggregate_member_scores(lesson_session, pe_settings):
    """集計して付与: グループ内メンバー評価を集計し、ContributionEvaluationを作成"""
    from collections import defaultdict
    
    member_score_list = pe_settings.member_scores or []
    if not member_score_list:
        return
    
    groups = Group.objects.filter(lesson_session=lesson_session)
    evals = PeerEvaluation.objects.filter(lesson_session=lesson_session)
    
    for group in groups:
        group_members = list(GroupMember.objects.filter(group=group).select_related('student'))
        G = len(group_members)
        if G == 0:
            continue
        
        # 内部ポイント集計: G-N点 (Nは与えられた順位)
        internal_points = defaultdict(int)
        for member in group_members:
            internal_points[member.student_id] = 0
        
        group_evals = evals.filter(evaluator_group=group)
        for ev in group_evals:
            response = ev.response_json or {}
            for entry in response.get('group_members_eval', []):
                member_id = entry.get('member_id')
                rank = entry.get('rank')
                if member_id and rank:
                    internal_points[member_id] += (G - rank)
        
        # ポイント降順でソート
        sorted_members = sorted(internal_points.items(), key=lambda x: x[1], reverse=True)
        
        # 同点（タイ）対応: 同じポイントのメンバーには同じ順位の点数を付与
        # まず既存のContributionEvaluationを削除（このグループの集計分）
        ContributionEvaluation.objects.filter(
            peer_evaluation__lesson_session=lesson_session,
            peer_evaluation__evaluator_group=group,
        ).delete()
        
        # ダミーのピア評価を取得（集計結果保存用）
        aggregate_eval = group_evals.first()
        if not aggregate_eval:
            continue
        
        current_rank = 0
        prev_points = None
        for idx, (member_id, points) in enumerate(sorted_members):
            if points != prev_points:
                current_rank = idx  # 0-indexed
                prev_points = points
            
            score = member_score_list[current_rank] if current_rank < len(member_score_list) else 0
            if score > 0:
                try:
                    member = Student.objects.get(id=member_id)
                    ContributionEvaluation.objects.create(
                        peer_evaluation=aggregate_eval,
                        evaluatee=member,
                        contribution_score=score
                    )
                except Student.DoesNotExist:
                    pass

@login_required
def peer_evaluation_results(request, session_id):
    """ピア評価結果表示"""
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    lesson_session = _get_session_for_teacher_or_admin(request, session_id)
    
    evaluations = PeerEvaluation.objects.filter(lesson_session=lesson_session).select_related('evaluator_group')
    groups = Group.objects.filter(lesson_session=lesson_session)
    
    # response_jsonからグループ別得票を集計
    from collections import defaultdict
    group_vote_counts = defaultdict(lambda: defaultdict(int))  # {group_id: {rank: count}}
    
    pe_settings = None
    if lesson_session.peer_evaluation_configured:
        pe_settings = lesson_session.peer_evaluation_settings
    
    group_score_list = pe_settings.group_scores if pe_settings else []
    group_rank_headers = [
        {'rank': idx + 1, 'points': point}
        for idx, point in enumerate(group_score_list)
    ]
    
    for ev in evaluations:
        response = ev.response_json or {}
        for entry in response.get('other_group_eval', []):
            gid = entry.get('group_id')
            rank = entry.get('rank')
            if gid and rank:
                group_vote_counts[gid][rank] += 1

    aggregate_group_scores = {}
    aggregate_internal_points = {}
    if (
        pe_settings
        and pe_settings.enable_group_evaluation
        and pe_settings.group_evaluation_method == PeerEvaluationSettings.EvaluationMethod.AGGREGATE
        and lesson_session.peer_evaluation_status == LessonSession.PeerEvaluationStatus.CLOSED
    ):
        group_ids = [g.id for g in groups]
        group_count = len(group_ids)
        aggregate_internal_points = {gid: 0 for gid in group_ids}
        for ev in evaluations:
            response = ev.response_json or {}
            for entry in response.get('other_group_eval', []):
                gid = entry.get('group_id')
                rank = entry.get('rank')
                if gid in aggregate_internal_points and rank and 1 <= rank <= group_count:
                    aggregate_internal_points[gid] += (group_count - rank)

        sorted_groups_internal = sorted(
            aggregate_internal_points.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        current_rank = 0
        prev_points = None
        for idx, (gid, internal_points) in enumerate(sorted_groups_internal):
            if internal_points != prev_points:
                current_rank = idx
                prev_points = internal_points
            aggregate_group_scores[gid] = group_score_list[current_rank] if current_rank < len(group_score_list) else 0
    
    group_stats = {}
    for group in groups:
        votes = group_vote_counts.get(group.id, {})
        if aggregate_group_scores:
            total_score = aggregate_group_scores.get(group.id, 0)
        else:
            total_score = 0
            for rank, count in votes.items():
                if rank - 1 < len(group_score_list):
                    total_score += group_score_list[rank - 1] * count
        votes_by_rank_list = [votes.get(idx + 1, 0) for idx in range(len(group_score_list))]
        
        evaluations_given = evaluations.filter(evaluator_group=group).count()
        
        group_stats[group.id] = {
            'group': group,
            'votes_by_rank': dict(votes),
            'votes_by_rank_list': votes_by_rank_list,
            'internal_points': aggregate_internal_points.get(group.id, 0),
            'total_score': total_score,
            'evaluations_given': evaluations_given,
            'score': total_score,
        }
    
    sorted_groups = sorted(group_stats.values(), key=lambda x: x['score'], reverse=True)

    enrolled_students = lesson_session.classroom.students.filter(role='student').order_by('full_name')
    group_name_map = {group.id: group.display_name for group in groups}
    student_name_map = {student.id: student.full_name for student in enrolled_students}

    submission_map = {}
    for evaluation in evaluations.order_by('student_id', '-created_at'):
        student_id = evaluation.student_id
        if student_id not in submission_map:
            submission_map[student_id] = evaluation

    student_rows = []
    submitted_count = 0
    for enrolled_student in enrolled_students:
        submission = submission_map.get(enrolled_student.id)
        is_submitted = submission is not None
        if is_submitted:
            submitted_count += 1
        student_rows.append({
            'student': enrolled_student,
            'email': enrolled_student.email,
            'submitted': is_submitted,
            'submitted_at': submission.created_at if submission else None,
            'submission_detail': _build_submission_detail(submission, group_name_map, student_name_map) if submission else None,
        })

    total_students = enrolled_students.count()
    submission_rate = round((submitted_count / total_students) * 100, 1) if total_students else 0

    comment_rows = []
    for evaluation in evaluations:
        response = evaluation.response_json or {}
        group_reasons = [
            entry for entry in response.get('other_group_eval', [])
            if entry.get('reason')
        ]
        member_reasons = [
            entry for entry in response.get('group_members_eval', [])
            if entry.get('reason')
        ]
        if group_reasons or member_reasons or evaluation.general_comment:
            comment_rows.append({
                'evaluation': evaluation,
                'group_reasons': group_reasons,
                'member_reasons': member_reasons,
            })
    
    context = {
        'lesson_session': lesson_session,
        'evaluations': evaluations,
        'group_stats': sorted_groups,
        'group_rank_headers': group_rank_headers,
        'total_evaluations': evaluations.count(),
        'total_groups': groups.count(),
        'submission_rows': student_rows,
        'submitted_count': submitted_count,
        'total_students': total_students,
        'submission_rate': submission_rate,
        'pe_settings': pe_settings,
        'comment_rows': comment_rows,
    }
    
    return render(request, 'school_management/peer_evaluation_results.html', context)

@login_required
def delete_all_peer_evaluations(request, session_id):
    """ピア評価データを全て削除"""
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        messages.error(request, '権限がありません。')
        return redirect('school_management:dashboard')
    lesson_session = _get_session_for_teacher_or_admin(request, session_id)
    
    if request.method == 'POST':
        # ピア評価データを削除（紐づく貢献度評価も自動削除され、ポイントも再計算されます）
        count = PeerEvaluation.objects.filter(lesson_session=lesson_session).count()
        PeerEvaluation.objects.filter(lesson_session=lesson_session).delete()
        
        messages.success(request, f'{count}件のピア評価データを削除し、リセットしました。')
        
    return redirect('school_management:peer_evaluation_results', session_id=session_id)

@login_required
def peer_evaluation_settings_view(request, session_id):
    """ピア評価設定管理画面（管理者用）"""
    lesson_session = get_object_or_404(
        LessonSession,
        id=session_id,
        classroom__teachers=request.user
    )
    
    # 受付開始済みの設定は変更不可
    if lesson_session.peer_evaluation_status != LessonSession.PeerEvaluationStatus.NOT_OPEN:
        messages.warning(request, '受付開始済みのピア評価設定は変更できません。')
        return redirect('school_management:session_detail', session_id=session_id)
    
    # 既存設定を取得（なければNone）
    try:
        pe_settings = lesson_session.peer_evaluation_settings
    except PeerEvaluationSettings.DoesNotExist:
        pe_settings = None
    
    # テンプレートコピー処理
    if request.method == 'POST' and request.POST.get('action') == 'copy_template':
        source_session_id = request.POST.get('source_session_id')
        if source_session_id:
            try:
                source_session = LessonSession.objects.get(
                    id=source_session_id,
                    classroom=lesson_session.classroom,
                )
                source_settings = source_session.peer_evaluation_settings
                if pe_settings:
                    pe_settings.enable_member_evaluation = source_settings.enable_member_evaluation
                    pe_settings.member_scores = source_settings.member_scores
                    pe_settings.member_reason_control = source_settings.member_reason_control
                    pe_settings.evaluation_method = source_settings.evaluation_method
                    pe_settings.enable_group_evaluation = source_settings.enable_group_evaluation
                    pe_settings.group_scores = source_settings.group_scores
                    pe_settings.group_reason_control = source_settings.group_reason_control
                    pe_settings.group_evaluation_method = source_settings.group_evaluation_method
                    pe_settings.show_points = source_settings.show_points
                    pe_settings.save()
                else:
                    pe_settings = PeerEvaluationSettings.objects.create(
                        lesson_session=lesson_session,
                        enable_member_evaluation=source_settings.enable_member_evaluation,
                        member_scores=source_settings.member_scores,
                        member_reason_control=source_settings.member_reason_control,
                        evaluation_method=source_settings.evaluation_method,
                        enable_group_evaluation=source_settings.enable_group_evaluation,
                        group_scores=source_settings.group_scores,
                        group_reason_control=source_settings.group_reason_control,
                        group_evaluation_method=source_settings.group_evaluation_method,
                        show_points=source_settings.show_points,
                    )
                # 一般設定もコピー
                lesson_session.enable_comments = source_session.enable_comments
                lesson_session.enable_feedback = source_session.enable_feedback
                lesson_session.save()
                messages.success(request, f'第{source_session.session_number}回の設定をコピーしました。')
            except (LessonSession.DoesNotExist, PeerEvaluationSettings.DoesNotExist):
                messages.error(request, 'コピー元の設定が見つかりません。')
        return redirect('school_management:peer_evaluation_settings', session_id=session_id)
    
    if request.method == 'POST' and request.POST.get('action') != 'copy_template':
        # 一般設定
        lesson_session.enable_comments = request.POST.get('enable_comments') == 'on'
        lesson_session.enable_feedback = request.POST.get('enable_feedback') == 'on'
        lesson_session.save()
        
        # メンバー評価配点をリストで取得
        member_scores_raw = request.POST.get('member_scores_json', '[]')
        try:
            member_scores = json.loads(member_scores_raw)
            if not isinstance(member_scores, list):
                member_scores = []
            member_scores = [max(0, int(s)) for s in member_scores]
        except (json.JSONDecodeError, ValueError, TypeError):
            member_scores = []
        
        # グループ評価配点をリストで取得
        group_scores_raw = request.POST.get('group_scores_json', '[]')
        try:
            group_scores = json.loads(group_scores_raw)
            if not isinstance(group_scores, list):
                group_scores = []
            group_scores = [max(0, int(s)) for s in group_scores]
        except (json.JSONDecodeError, ValueError, TypeError):
            group_scores = []
        
        settings_data = {
            'enable_member_evaluation': request.POST.get('enable_member_evaluation') == 'on',
            'member_scores': member_scores,
            'member_reason_control': request.POST.get('member_reason_control', PeerEvaluationSettings.ReasonMode.DISABLED),
            'evaluation_method': request.POST.get('evaluation_method', PeerEvaluationSettings.EvaluationMethod.DIRECT),
            'enable_group_evaluation': request.POST.get('enable_group_evaluation') == 'on',
            'group_scores': group_scores,
            'group_reason_control': request.POST.get('group_reason_control', PeerEvaluationSettings.ReasonMode.DISABLED),
            'group_evaluation_method': request.POST.get('group_evaluation_method', PeerEvaluationSettings.EvaluationMethod.DIRECT),
            'show_points': request.POST.get('show_points') == 'on',
        }

        valid_reason_modes = {value for value, _ in PeerEvaluationSettings.ReasonMode.choices}
        valid_eval_methods = {value for value, _ in PeerEvaluationSettings.EvaluationMethod.choices}
        if settings_data['member_reason_control'] not in valid_reason_modes:
            settings_data['member_reason_control'] = PeerEvaluationSettings.ReasonMode.DISABLED
        if settings_data['group_reason_control'] not in valid_reason_modes:
            settings_data['group_reason_control'] = PeerEvaluationSettings.ReasonMode.DISABLED
        if settings_data['evaluation_method'] not in valid_eval_methods:
            settings_data['evaluation_method'] = PeerEvaluationSettings.EvaluationMethod.DIRECT
        if settings_data['group_evaluation_method'] not in valid_eval_methods:
            settings_data['group_evaluation_method'] = PeerEvaluationSettings.EvaluationMethod.DIRECT

        if settings_data['enable_member_evaluation'] and not settings_data['member_scores']:
            messages.error(request, 'メンバー評価を有効にする場合は、配点を1つ以上設定してください。')
            return redirect('school_management:peer_evaluation_settings', session_id=session_id)
        if settings_data['enable_group_evaluation'] and not settings_data['group_scores']:
            messages.error(request, '他グループ評価を有効にする場合は、配点を1つ以上設定してください。')
            return redirect('school_management:peer_evaluation_settings', session_id=session_id)
        
        if pe_settings:
            for key, value in settings_data.items():
                setattr(pe_settings, key, value)
            pe_settings.save()
        else:
            pe_settings = PeerEvaluationSettings.objects.create(
                lesson_session=lesson_session,
                **settings_data
            )
        
        messages.success(request, 'ピア評価設定を保存しました。')
        return redirect('school_management:session_detail', session_id=session_id)
    
    # テンプレートコピー用: 同じクラスの他の授業回で設定済みのもの
    template_sessions = LessonSession.objects.filter(
        classroom=lesson_session.classroom,
        peer_evaluation_settings__isnull=False,
    ).exclude(id=lesson_session.id).order_by('-session_number')
    
    context = {
        'lesson_session': lesson_session,
        'pe_settings': pe_settings,
        'template_sessions': template_sessions,
        'reason_mode_choices': PeerEvaluationSettings.ReasonMode.choices,
        'evaluation_method_choices': PeerEvaluationSettings.EvaluationMethod.choices,
    }
    return render(request, 'school_management/peer_evaluation_settings_full.html', context)
