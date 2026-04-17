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
    """ピア評価フォーム（設定に基づいて動的に生成）"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # ピア評価設定が完了しているか確認
    if not lesson_session.peer_evaluation_configured:
        context = {
            'lesson_session': lesson_session,
            'error_message': '教員がピア評価を設定していません。',
            'is_configuration_error': True,
        }
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
    
    # ✅ ピア評価の締切を確認
    if lesson_session.peer_evaluation_closed:
        context = {
            'lesson_session': lesson_session,
            'error_message': 'ピア評価の締切が過ぎています。提出はできません。',
            'is_closed': True,
        }
        return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
    
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student')
    oauth_session, student = _load_verified_oauth_session(request, lesson_session)

    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'requires_google_auth': False,
        'enable_comments': lesson_session.enable_comments,
        'enable_member_evaluation': lesson_session.enable_member_evaluation,
        'enable_group_evaluation': lesson_session.enable_group_evaluation,
        'enable_feedback': lesson_session.enable_feedback,
        'member_ranking_count': lesson_session.member_ranking_count,
        'group_ranking_count': lesson_session.group_ranking_count,
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
    evaluator_group_members = list(
        GroupMember.objects.filter(group=evaluator_group)
        .exclude(student=student)
        .select_related('student')
        .values_list('student__full_name', flat=True)
    )
    # ✅ テンプレート用：student_idとfull_nameを含むオブジェクトリスト
    evaluator_group_member_objects = list(
        GroupMember.objects.filter(group=evaluator_group)
        .exclude(student=student)
        .select_related('student')
        .values('student__id', 'student__full_name')
    )
    evaluator_group_member_names = evaluator_group_members
    
    # 他グループを取得（グループ評価用）
    other_groups = groups.exclude(id=evaluator_group.id)
    # ✅ order_by で確定的な順序でsorting（group_number → id）
    ordered_other_groups = list(other_groups.order_by('group_number', 'id'))
    
    # ===== 上位N名/Xグループの制限ロジック =====
    # ✅ メンバー評価対象数: 設定値(member_ranking_count) と利用可能メンバー数(自分以外)の少ない方
    # 例: member_ranking_count=3, チーム6人(自分以外5人) → 3位まで表示・選択可能
    # 例: member_ranking_count=10, チーム4人(自分以外3人) → 3位まで表示・選択可能
    max_member_rank = min(lesson_session.member_ranking_count, len(evaluator_group_members))
    
    # ✅ グループ評価対象数: 「自分以外のすべてのグループ」が選択可能
    # ユーザーが設定する「グループ順位数」は「フォームに表示する最大ランク数」として機能
    # 実際の選択肢は「すべての他グループ」を対象にする
    max_group_rank = other_groups.count()  # 自分以外のグループすべてが対象
    
    # ✅ メンバー順位リスト: 実行する機構数に応じた最大順位数まで表示する
    member_ranking_list = [
        {'rank': i, 'points': lesson_session.member_scores.get(str(i), 0)}
        for i in range(1, max_member_rank + 1)
    ]
    
    # ✅ グループ順位リスト: 実行する他グループ数に応じた最大順位数まで表示する
    group_ranking_list = [
        {'rank': i, 'points': lesson_session.group_scores.get(str(i), 0)}
        for i in range(1, max_group_rank + 1)
    ]
    
    # ✅ 制限対象のグループIDリストを作成
    # バリデーション用：表示ランク数（lesson_session.group_ranking_count）までのグループを記録
    restricted_group_ids = set()
    if lesson_session.enable_group_evaluation and len(ordered_other_groups) > 0:
        # display_group_rank = lesson_session.group_ranking_count を表示ランク数とする
        display_group_rank = min(lesson_session.group_ranking_count, len(ordered_other_groups))
        for i in range(display_group_rank):
            restricted_group_ids.add(ordered_other_groups[i].id)
    
    # テンプレート用：すべての他グループを表示（ドロップダウン用）
    restricted_other_groups = ordered_other_groups

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
        # ✅ POST前に再度締切チェック（セキュリティ）
        if lesson_session.peer_evaluation_closed:
            messages.error(request, 'ピア評価の締切が過ぎています。提出はできません。')
            context.update({
                'authenticated_student': student,
                'evaluator_group': evaluator_group if 'evaluator_group' in locals() else None,
                'is_closed': True,
            })
            return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
        
        # ===== バリデーション =====
        validation_errors = []
        
        # ✅ グループ評価の必須チェック + 重複チェック
        if lesson_session.enable_group_evaluation:
            group_selections = {}
            for rank_item in group_ranking_list:
                rank = rank_item['rank']
                group_id = request.POST.get(f'group_rank_{rank}')
                
                # ✅ 必須チェック: グループ評価の各ランクが入力されているか
                if not group_id:
                    validation_errors.append(f'❌ グループ評価の{rank}位：グループを選択してください。')
                    continue
                
                # 全ランク間の重複チェック
                if group_id in group_selections.values():
                    validation_errors.append(f'❌ グループ評価：{rank}位に選ばれたグループは既に別の順位で選択されています。')
                    continue
                
                group_selections[rank] = group_id
                
                # ✅ 制限範囲外のグループが選ばれていないかチェック
                # 表示ランク数（lesson_session.group_ranking_count）までのグループのみOK
                allowed_group_ids = [str(g.id) for g in ordered_other_groups[:min(lesson_session.group_ranking_count, len(ordered_other_groups))]]
                if group_id not in allowed_group_ids:
                    max_allowed_rank = min(lesson_session.group_ranking_count, len(ordered_other_groups))
                    validation_errors.append(f'❌ グループ評価の{rank}位：評価対象外のグループが選ばれています。最大{max_allowed_rank}位までのグループを選択してください。')
        
        # ✅ メンバー評価の必須チェック + 重複チェック
        if lesson_session.enable_member_evaluation:
            member_selections = {}
            for rank in range(1, max_member_rank + 1):
                member_id = request.POST.get(f'member_rank_{rank}')
                
                # ✅ 必須チェック: メンバー評価の各ランクが入力されているか
                if not member_id:
                    validation_errors.append(f'❌ チームメンバー評価の{rank}位：メンバーを選択してください。')
                    continue
                
                # 全ランク間の重複チェック
                if member_id in member_selections.values():
                    validation_errors.append(f'❌ チームメンバー評価：{rank}位に選ばれたメンバーは既に別の順位で選択されています。')
                    continue
                
                member_selections[rank] = member_id
        
        # バリデーションエラーがあれば、フォームを再表示
        if validation_errors:
            context.update({
                'authenticated_student': student,
                'evaluator_group': evaluator_group,
                'evaluator_group_member_names': evaluator_group_member_names,
                'evaluator_group_member_objects': evaluator_group_member_objects,  # ✅ 追加
                'other_groups': restricted_other_groups,
                'member_scores': lesson_session.member_scores,
                'group_scores': lesson_session.group_scores,
                'member_scores_json': json.dumps(lesson_session.member_scores),
                'group_scores_json': json.dumps(lesson_session.group_scores),
                'member_ranking_list': member_ranking_list,
                'group_ranking_list': group_ranking_list,
                'max_member_rank': max_member_rank,
                'max_group_rank': max_group_rank,
                'validation_errors': validation_errors,
            })
            return render(request, 'school_management/improved_peer_evaluation_form_full.html', context)
        
        # バリデーション成功後、評価を保存
        try:
            # グループ評価の保存処理
            first_place_group = None
            second_place_group = None
            
            if lesson_session.enable_group_evaluation:
                # ✅ group_ranking_count に合わせて動的にランクを処理（最大10位まで対応）
                group_ranks = {}
                group_selections_dict = {}  # JSON保存用
                
                for rank in range(1, lesson_session.group_ranking_count + 1):
                    group_id = request.POST.get(f'group_rank_{rank}')
                    if group_id:
                        try:
                            group_obj = Group.objects.get(id=group_id, lesson_session=lesson_session)
                            group_ranks[rank] = group_obj
                            group_selections_dict[str(rank)] = int(group_id)  # JSON用：文字列キーで保存
                        except (Group.DoesNotExist, ValueError):
                            pass
                
                first_place_group = group_ranks.get(1)
                second_place_group = group_ranks.get(2)
            else:
                group_selections_dict = {}
            
            # ✅ メンバー選択をJSON保存用に準備
            member_selections_dict = {}
            if lesson_session.enable_member_evaluation:
                for rank in range(1, max_member_rank + 1):
                    member_id = request.POST.get(f'member_rank_{rank}')
                    if member_id:
                        try:
                            int(member_id)  # 検証のみ
                            member_selections_dict[str(rank)] = int(member_id)  # JSON用
                        except (ValueError, TypeError):
                            pass
            
            # ピア評価を保存
            peer_evaluation = PeerEvaluation.objects.create(
                lesson_session=lesson_session,
                student=student,
                email=_normalize_email(oauth_session.email),
                evaluator_token=str(uuid.uuid4()),
                evaluator_group=evaluator_group,
                first_place_group=first_place_group,
                second_place_group=second_place_group,
                general_comment=request.POST.get('general_comment', ''),
                # ✅ enable_feedback 有効時は feedback を class_comment に保存
                class_comment=request.POST.get('feedback', '') if lesson_session.enable_feedback else '',
                group_selections=group_selections_dict,
                member_selections=member_selections_dict,
            )
            
            # ✅ メンバー評価と貢献度スコアを保存
            if lesson_session.enable_member_evaluation:
                for rank in range(1, max_member_rank + 1):
                    member_id = request.POST.get(f'member_rank_{rank}')
                    if member_id:
                        try:
                            member = Student.objects.get(id=int(member_id), group_memberships__group=evaluator_group)
                            score = lesson_session.member_scores.get(str(rank), 0)
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
    
    # JSONをJavaScript用に変換
    member_scores_json = json.dumps(lesson_session.member_scores)
    group_scores_json = json.dumps(lesson_session.group_scores)
    
    context.update({
        'authenticated_student': student,
        'evaluator_group': evaluator_group,
        'evaluator_group_member_names': evaluator_group_member_names,
        'evaluator_group_member_objects': evaluator_group_member_objects,  # ✅ 追加
        'other_groups': restricted_other_groups,
        'member_scores': lesson_session.member_scores,
        'group_scores': lesson_session.group_scores,
        'member_scores_json': member_scores_json,
        'group_scores_json': group_scores_json,
        'member_ranking_list': member_ranking_list,
        'group_ranking_list': group_ranking_list,
        'max_member_rank': max_member_rank,
        'max_group_rank': max_group_rank,
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
            'enable_comments': lesson_session.enable_comments,
        }
        return render(request, 'school_management/improved_peer_evaluation_form_simple.html', context)
        
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

    # 学生ごとの最新提出をまとめて取得してマップ化（N+1クエリ回避）
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

@login_required
def peer_evaluation_settings_view(request, session_id):
    """ピア評価設定管理画面（管理者用）"""
    lesson_session = get_object_or_404(
        LessonSession,
        id=session_id,
        classroom__teachers=request.user
    )
    
    if request.method == 'POST':
        # 一般設定
        lesson_session.enable_comments = request.POST.get('enable_comments') == 'on'
        lesson_session.enable_feedback = request.POST.get('enable_feedback') == 'on'
        
        # ✅ メンバー評価設定（バリデーション付き）
        lesson_session.enable_member_evaluation = request.POST.get('enable_member_evaluation') == 'on'
        if lesson_session.enable_member_evaluation:
            try:
                member_ranking_count = int(request.POST.get('member_ranking_count', 2))
                # 範囲チェック: 1～10位
                if not (1 <= member_ranking_count <= 10):
                    messages.error(request, 'メンバー順位数は1～10の間で設定してください。')
                    member_ranking_count = lesson_session.member_ranking_count
            except (ValueError, TypeError):
                messages.error(request, 'メンバー順位数が無効な値です。')
                member_ranking_count = lesson_session.member_ranking_count
            
            lesson_session.member_ranking_count = member_ranking_count
            
            # メンバー配点をJSONで保存（バリデーション付き）
            member_scores = {}
            for i in range(1, member_ranking_count + 1):
                try:
                    score = int(request.POST.get(f'member_score_{i}', 0))
                    member_scores[str(i)] = max(0, score)  # 負の値を0に
                except (ValueError, TypeError):
                    messages.error(request, f'メンバー{i}位のスコアが無効です。')
                    member_scores[str(i)] = 0
            lesson_session.member_scores = member_scores
        
        # ✅ グループ評価設定（バリデーション付き）
        lesson_session.enable_group_evaluation = request.POST.get('enable_group_evaluation') == 'on'
        if lesson_session.enable_group_evaluation:
            try:
                group_ranking_count = int(request.POST.get('group_ranking_count', 2))
                # 範囲チェック: 1～10位
                if not (1 <= group_ranking_count <= 10):
                    messages.error(request, 'グループ順位数は1～10の間で設定してください。')
                    group_ranking_count = lesson_session.group_ranking_count
            except (ValueError, TypeError):
                messages.error(request, 'グループ順位数が無効な値です。')
                group_ranking_count = lesson_session.group_ranking_count
            
            lesson_session.group_ranking_count = group_ranking_count
            
            # グループ配点をJSONで保存（バリデーション付き）
            group_scores = {}
            for i in range(1, group_ranking_count + 1):
                try:
                    score = int(request.POST.get(f'group_score_{i}', 0))
                    group_scores[str(i)] = max(0, score)  # 負の値を0に
                except (ValueError, TypeError):
                    messages.error(request, f'グループ{i}位のスコアが無効です。')
                    group_scores[str(i)] = 0
            lesson_session.group_scores = group_scores
        
        lesson_session.peer_evaluation_configured = True
        lesson_session.save()
        
        messages.success(request, 'ピア評価設定を保存しました。')
        return redirect('school_management:session_detail', session_id=session_id)
    
    # JSONをJavaScript用に変換
    member_scores_json = json.dumps({str(k): v for k, v in lesson_session.member_scores.items()})
    group_scores_json = json.dumps({str(k): v for k, v in lesson_session.group_scores.items()})
    
    context = {
        'lesson_session': lesson_session,
        'enable_comments': lesson_session.enable_comments,
        'enable_feedback': lesson_session.enable_feedback,
        'enable_member_evaluation': lesson_session.enable_member_evaluation,
        'member_ranking_count': lesson_session.member_ranking_count,
        'member_scores_json': member_scores_json,
        'enable_group_evaluation': lesson_session.enable_group_evaluation,
        'group_ranking_count': lesson_session.group_ranking_count,
        'group_scores_json': group_scores_json,
    }
    return render(request, 'school_management/peer_evaluation_settings_full.html', context)