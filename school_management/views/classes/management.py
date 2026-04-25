from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.middleware.csrf import get_token
from django.contrib import messages
from ...models import ClassRoom
import datetime

@login_required
def class_create_view(request):
    """
    クラス作成機能
    
    POSTリクエスト時に、画面から送信されたクラス情報を取得し、
    新規クラス(ClassRoom)レコードを作成する。
    また、作成者を担当教員として自動的に紐付ける。
    """
    if request.method == 'POST':
        # フォームから送信された基本情報を取得
        class_name = request.POST.get('class_name')
        year = request.POST.get('year')
        semester = request.POST.get('semester')
        
        # 画面から送信された評価システムの値を取得
        raw_grading_system = request.POST.get('grading_system', 'default')
        
        # バリデーション: モデルで許可されている値か検証を行う
        # 許可されていない不正な値が送信された場合は、安全のため強制的に'default'を設定する
        valid_systems = [choice[0] for choice in ClassRoom.GRADING_SYSTEM_CHOICES]
        if raw_grading_system in valid_systems:
            grading_system = raw_grading_system
        else:
            grading_system = 'default'
        
        if class_name and year and semester:
            try:
                # ClassRoomレコードを新規作成
                classroom = ClassRoom.objects.create(
                    class_name=class_name,
                    year=int(year),
                    semester=semester,
                    grading_system=grading_system  # 検証済みの値を保存
                )
                # 担当教員として現在のユーザーを追加
                classroom.teachers.add(request.user)
                messages.success(request, 'クラスを作成しました。')
                return redirect('school_management:class_list')
            except ValueError:
                # 年度の数値変換に失敗した場合のエラーハンドリング
                messages.error(request, '年度は数値で入力してください。')
        else:
            messages.error(request, '必須項目を入力してください。')

    # GETリクエスト、またはPOSTでエラーがあった場合に表示するコンテキストを準備
    now = datetime.datetime.now()
    current_year = now.year
    current_month = now.month

    # 年度範囲の設定（現在の年から-5年、+5年）
    year_range_min = current_year - 5
    year_range_max = current_year + 5

    # 学期のデフォルト設定
    # 4月～8月: 「前期」
    # 9月～3月: 「後期」
    if 4 <= current_month <= 8:
        default_semester = 'first'
    else:
        default_semester = 'second'

    context = {
        'csrf_token': get_token(request),
        'default_year': current_year,
        'year_range_min': year_range_min,
        'year_range_max': year_range_max,
        'default_semester': default_semester,
    }
    # POSTでエラーがあった場合、入力値を復元するためにcontextに追加
    if request.method == 'POST':
        context['form_data'] = request.POST

    return render(request, 'school_management/class_create.html', context)

@login_required
@require_POST
def class_delete_view(request, class_id):
    """
    クラス削除機能
    
    指定されたIDのクラスをデータベースから削除する。
    セキュリティ対策として、ログイン中のユーザーが担当しているクラスのみ削除可能とする。
    """
    # 担当教員として紐づいているクラスのみ取得（他人のクラスを削除できないように保護）
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    try:
        class_name = classroom.class_name
        classroom.delete()
        messages.success(request, f'クラス「{class_name}」を削除しました。')
    except Exception as e:
        messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
        
    return redirect('school_management:class_list')