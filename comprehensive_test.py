#!/usr/bin/env python
"""
包括的なテストスクリプト
- N+1クエリ問題検査
- バックエンド処理検証
- データベース処理
"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_project.settings')
django.setup()

from django.test.utils import CaptureQueriesContext
from django.db import connection
from school_management.models import (
    ClassRoom, CustomUser, LessonSession, StudentClassPoints,
    StudentLessonPoints, QuizScore, PeerEvaluation, GroupMember,
    ContributionEvaluation, QRCodeScan, SelfEvaluation
)
from django.db.models import Prefetch
import json
from datetime import datetime, timedelta

class TestResults:
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'tests': [],
            'summary': {
                'total': 0,
                'passed': 0,
                'failed': 0,
                'issues': []
            }
        }
    
    def add_test(self, name, status, query_count=None, details=None):
        test = {
            'name': name,
            'status': status,
            'query_count': query_count,
            'details': details or {}
        }
        self.results['tests'].append(test)
        self.results['summary']['total'] += 1
        if status == 'PASS':
            self.results['summary']['passed'] += 1
        else:
            self.results['summary']['failed'] += 1
            if details:
                self.results['summary']['issues'].append(f"{name}: {details}")
    
    def save(self):
        with open('/home/noebo/job_projects/grades/TEST_RESULTS.json', 'w') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        print(f"\n✅ テスト結果: {self.results['summary']['passed']}/{self.results['summary']['total']} 成功")

results = TestResults()

# ========== テスト1: N+1クエリ問題検査 ==========
print("\n🔍 テスト1: N+1クエリ問題検査")
print("=" * 60)

# クラス一覧取得
classrooms = ClassRoom.objects.all()
if classrooms.exists():
    classroom = classrooms.first()
    
    # Test 1.1: StudentClassPoints取得のN+1
    print("\n📊 Test 1.1: StudentClassPoints一覧")
    with CaptureQueriesContext(connection) as context:
        points_list = list(StudentClassPoints.objects.filter(classroom=classroom)[:5])
        for sp in points_list:
            _ = sp.student.full_name
            _ = sp.total_points
    
    query_count = len(context)
    status = 'PASS' if query_count <= 5 else 'WARN'
    results.add_test('StudentClassPoints N+1', status, query_count, 
                     f"期待: ≤5, 実績: {query_count}")
    print(f"   クエリ数: {query_count} (期待: ≤5)")
    
    # Test 1.2: LessonSession + PeerEvaluation
    print("\n📊 Test 1.2: LessonSession+PeerEvaluation")
    sessions = LessonSession.objects.filter(classroom=classroom)[:3]
    with CaptureQueriesContext(connection) as context:
        for session in sessions:
            evals = PeerEvaluation.objects.filter(lesson_session=session)
            _ = list(evals)
    
    query_count = len(context)
    status = 'PASS' if query_count <= 4 else 'WARN'
    results.add_test('PeerEvaluation N+1', status, query_count,
                     f"期待: ≤4, 実績: {query_count}")
    print(f"   クエリ数: {query_count} (期待: ≤4)")
    
    # Test 1.3: GroupMember + Student
    print("\n📊 Test 1.3: GroupMember+Student")
    from school_management.models import Group
    groups = Group.objects.filter(lesson_session__classroom=classroom)[:3]
    with CaptureQueriesContext(connection) as context:
        for group in groups:
            members = list(group.groupmember_set.all())
            for m in members:
                _ = m.student.email
    
    query_count = len(context)
    status = 'WARN' if query_count > 10 else 'PASS'
    results.add_test('GroupMember N+1', status, query_count,
                     f"期待: ≤10, 実績: {query_count}")
    print(f"   クエリ数: {query_count} (期待: ≤10)")

# ========== テスト2: バックエンド処理 ==========
print("\n\n🔧 テスト2: バックエンド処理検証")
print("=" * 60)

if classrooms.exists():
    classroom = classrooms.first()
    
    # Test 2.1: 成績計算処理
    print("\n📈 Test 2.1: 成績計算処理")
    try:
        points = StudentClassPoints.objects.filter(classroom=classroom).first()
        if points:
            total = points.total_points
            print(f"   成績計算: OK (合計: {total}点)")
            results.add_test('成績計算', 'PASS')
        else:
            results.add_test('成績計算', 'WARN', details='成績データなし')
    except Exception as e:
        results.add_test('成績計算', 'FAIL', details=str(e))
        print(f"   ❌ エラー: {e}")
    
    # Test 2.2: 平均点計算
    print("\n📊 Test 2.2: 平均点計算")
    try:
        avg = classroom.get_average_points()
        print(f"   平均点: {avg}点")
        results.add_test('平均点計算', 'PASS')
    except Exception as e:
        results.add_test('平均点計算', 'FAIL', details=str(e))
        print(f"   ❌ エラー: {e}")
    
    # Test 2.3: クイズスコア集計
    print("\n📝 Test 2.3: クイズスコア集計")
    try:
        quiz_scores = QuizScore.objects.filter(quiz__classroom=classroom)
        count = quiz_scores.count()
        print(f"   クイズスコア数: {count}")
        if count > 0:
            avg_score = sum(qs.score for qs in quiz_scores[:10]) / min(10, count)
            print(f"   平均スコア: {avg_score:.1f}")
        results.add_test('クイズ集計', 'PASS')
    except Exception as e:
        results.add_test('クイズ集計', 'FAIL', details=str(e))
        print(f"   ❌ エラー: {e}")

# ========== テスト3: データベース一貫性 ==========
print("\n\n🗄️  テスト3: データベース一貫性")
print("=" * 60)

# Test 3.1: 孤立したレコード検査
print("\n🔎 Test 3.1: 孤立したレコード検査")
try:
    orphan_scores = StudentClassPoints.objects.filter(student__isnull=True)
    if orphan_scores.exists():
        results.add_test('孤立レコード検査', 'WARN', details=f"{orphan_scores.count()}件の孤立StudentClassPoints")
        print(f"   ⚠️  孤立StudentClassPoints: {orphan_scores.count()}件")
    else:
        results.add_test('孤立レコード検査', 'PASS')
        print("   ✅ 孤立レコードなし")
except Exception as e:
    results.add_test('孤立レコード検査', 'FAIL', details=str(e))

# Test 3.2: 外部キー参照の検証
print("\n🔎 Test 3.2: 外部キー参照検証")
try:
    # PeerEvaluationの参照検証
    invalid_refs = PeerEvaluation.objects.filter(lesson_session__isnull=True)
    if invalid_refs.exists():
        results.add_test('FK参照検証', 'WARN', details=f"{invalid_refs.count()}件のPeerEvaluation参照エラー")
        print(f"   ⚠️  参照エラー: {invalid_refs.count()}件")
    else:
        results.add_test('FK参照検証', 'PASS')
        print("   ✅ 参照エラーなし")
except Exception as e:
    results.add_test('FK参照検証', 'FAIL', details=str(e))

# ========== テスト4: API/ビュー応答 ==========
print("\n\n🌐 テスト4: API/ビュー応答テスト")
print("=" * 60)

print("\n📡 Test 4.1: ダッシュボード応答")
import requests
try:
    resp = requests.get('http://127.0.0.1:8000/dashboard/', timeout=5, allow_redirects=True)
    status_code = resp.status_code
    if status_code == 200:
        results.add_test('ダッシュボード応答', 'PASS')
        print(f"   ✅ ステータス: {status_code}")
    else:
        results.add_test('ダッシュボード応答', 'WARN', details=f"ステータス: {status_code}")
        print(f"   ⚠️  ステータス: {status_code}")
except Exception as e:
    results.add_test('ダッシュボード応答', 'FAIL', details=str(e))
    print(f"   ❌ エラー: {e}")

print("\n📡 Test 4.2: クラス一覧応答")
try:
    resp = requests.get('http://127.0.0.1:8000/classes/', timeout=5, allow_redirects=True)
    status_code = resp.status_code
    if status_code == 200:
        results.add_test('クラス一覧応答', 'PASS')
        print(f"   ✅ ステータス: {status_code}")
    else:
        results.add_test('クラス一覧応答', 'WARN', details=f"ステータス: {status_code}")
        print(f"   ⚠️  ステータス: {status_code}")
except Exception as e:
    results.add_test('クラス一覧応答', 'FAIL', details=str(e))
    print(f"   ❌ エラー: {e}")

# ========== テスト5: メディアクエリ検査 ==========
print("\n\n📱 テスト5: メディアクエリ検査")
print("=" * 60)

print("\n🔍 Test 5.1: ベーステンプレートCSS")
try:
    with open('/home/noebo/job_projects/grades/school_management/templates/school_management/base.html', 'r') as f:
        content = f.read()
    has_viewport = 'viewport' in content
    has_bootstrap = 'bootstrap' in content
    if has_viewport and has_bootstrap:
        results.add_test('レスポンシブ設定', 'PASS')
        print("   ✅ Viewport設定: あり")
        print("   ✅ Bootstrap: あり")
    else:
        results.add_test('レスポンシブ設定', 'WARN', details=f"Viewport: {has_viewport}, Bootstrap: {has_bootstrap}")
except Exception as e:
    results.add_test('レスポンシブ設定', 'FAIL', details=str(e))

print("\n🔍 Test 5.2: 静的ファイル検査")
try:
    css_path = '/home/noebo/job_projects/grades/school_management/static/school_management/css'
    if os.path.exists(css_path):
        css_files = [f for f in os.listdir(css_path) if f.endswith('.css')]
        print(f"   ✅ CSSファイル数: {len(css_files)}")
        results.add_test('静的ファイル', 'PASS', details=f"CSSファイル: {len(css_files)}個")
    else:
        results.add_test('静的ファイル', 'WARN', details='CSSディレクトリが見つかりません')
except Exception as e:
    results.add_test('静的ファイル', 'FAIL', details=str(e))

# 結果保存
print("\n" + "=" * 60)
results.save()
print(f"\n📄 詳細結果: /home/noebo/job_projects/grades/TEST_RESULTS.json")
