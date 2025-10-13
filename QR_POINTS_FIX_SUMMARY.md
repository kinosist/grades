# QRコードポイント問題の修正内容

## 発見された問題

### 1. QRコード一覧画面でのポイント表示が不正確
**問題**: `class_qr_codes.html`で`student.points`（総合ポイント）を表示していた  
**原因**: `CustomUser.points`は更新していないため常に0のまま  
**影響**: クラスQRコード一覧画面で正しいポイントが表示されない

### 2. QRコードスキャン時にポイントが増えない
**問題**: 授業セッションが存在しない場合、ポイントが加算されない  
**原因**: `current_session`がNoneの場合、ポイント加算処理がスキップされていた  
**影響**: 授業日以外にQRコードをスキャンしてもポイントが付与されない

---

## 修正内容

### 1. クラスQRコード一覧画面の修正

#### views.py (1772-1796行目)
```python
# 各学生のクラスポイントを取得して渡す
for student in students:
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
        'class_points': class_points  # クラスポイントを追加
    })
```

#### class_qr_codes.html (47行目)
```html
<!-- 修正前 -->
<span class="badge bg-success">ポイント: {{ qr_data.student.points }}</span>

<!-- 修正後 -->
<span class="badge bg-success">ポイント: {{ qr_data.class_points }}pt</span>
```

---

### 2. QRコードスキャン処理の修正

#### views.py (1859-1925行目)

**主な変更点**:

1. **URLパラメータからクラスIDを取得**
```python
# クラスIDをGETパラメータから取得
class_id = request.GET.get('class_id')
target_classroom = None
if class_id:
    try:
        target_classroom = ClassRoom.objects.get(id=class_id, teachers=request.user)
    except ClassRoom.DoesNotExist:
        pass
```

2. **授業セッションがなくてもポイント付与**
```python
# ポイントを更新（授業セッションがなくてもクラスが指定されていればポイント付与）
update_classroom = current_session.classroom if current_session else target_classroom

if update_classroom:
    # 授業セッションごとのポイント（セッションがある場合のみ）
    if current_session:
        # StudentLessonPoints を更新
        ...
    
    # クラス累計ポイントを更新（必ず更新）
    scp, scp_created = StudentClassPoints.objects.get_or_create(
        student=qr_code.student,
        classroom=update_classroom,
        defaults={'points': 0}
    )
    scp.points += 1
    scp.save()
```

3. **現在のクラスポイントを表示用に取得**
```python
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
    'classroom': update_classroom,
    'student_class_points': student_class_points,  # 現在のポイント
    'points_added': True if update_classroom else False,  # ポイント付与フラグ
    ...
}
```

---

### 3. スキャン成功画面の修正

#### qr_code_scan.html

**表示内容の改善**:
- クラス名を明確に表示
- 現在のクラスポイントを表示
- ポイントが付与されたかどうかを明示

```html
{% if points_added %}
    <p class="mb-2">
        <strong class="text-success">
            {{ qr_code.student.full_name }}さんのクラスポイントが +1 増加しました！
        </strong>
    </p>
    {% if student_class_points is not None %}
        <p class="mb-0">
            <strong>現在のクラスポイント:</strong> 
            <span class="badge bg-primary fs-6">{{ student_class_points }}pt</span>
        </p>
    {% endif %}
{% else %}
    <div class="alert alert-warning mt-2">
        クラスが指定されていないため、ポイントは付与されませんでした。
    </div>
{% endif %}
```

---

## 動作の流れ（修正後）

### ケース1: クラスQRコード一覧からスキャン（推奨）

```
1. 教員がクラス詳細画面 → 「QRコード一覧」をクリック
2. URL: /qr-codes/scan/{qr_code_id}?class_id={class_id}
3. スキャン処理:
   - class_idからクラスを特定
   - 授業セッションの有無に関係なく、クラスポイント +1
   - StudentLessonPoints（授業セッションがある場合のみ）+1
4. スキャン成功画面:
   - 「クラス: ○○○」表示
   - 「クラスポイント +1 増加」表示
   - 「現在のクラスポイント: XXpt」表示
```

### ケース2: 直接QRコードをスキャン

```
1. URL: /qr-codes/scan/{qr_code_id}（class_idなし）
2. スキャン処理:
   - 今日の授業セッションを検索
   - 授業セッションがある場合のみポイント付与
3. スキャン成功画面:
   - 授業がある場合: ポイント付与
   - 授業がない場合: 警告メッセージ表示
```

---

## テスト結果

全てのテストが正常にパス ✅

```
test_student_edit_does_not_update_points ... ok
test_update_class_points ... ok
test_update_overall_points_requires_class_id ... ok

Ran 3 tests in 2.944s
OK
```

---

## 利用上の注意

### 推奨される使い方
1. **クラス詳細画面から「QRコード一覧」にアクセス**
2. そこから各学生のQRコードをスキャン
3. → この方法なら、授業日でなくてもポイントが確実に加算されます

### クラスポイントの確認方法
- **クラスQRコード一覧**: 各学生のポイントが表示される
- **クラス詳細画面**: 学生一覧でポイント確認
- **スキャン成功画面**: スキャン直後に現在のポイントを確認

---

## 変更ファイル一覧

1. `school_management/views.py`
   - `class_qr_codes` 関数（1772-1796行目）
   - `qr_code_scan` 関数（1859-1952行目）

2. `school_management/templates/school_management/class_qr_codes.html`
   - ポイント表示部分（47行目）

3. `school_management/templates/school_management/qr_code_scan.html`
   - スキャン成功メッセージ全体（17-54行目）
   - スキャン情報カード（59-76行目）

---

## データベースへの影響

- マイグレーション不要
- 既存データへの影響なし
- `StudentClassPoints` が正しく更新されるようになった

---

## まとめ

### 修正前の問題
❌ QRコード一覧で常に0ptと表示  
❌ 授業日以外はQRコードスキャンでポイントが増えない  
❌ クラス詳細とQRコード一覧でポイントが一致しない

### 修正後の状態
✅ クラスポイントが正しく表示される  
✅ 授業日でなくてもクラス経由ならポイントが増える  
✅ 全ての画面でポイントが一致する  
✅ スキャン後に現在のポイントが確認できる

