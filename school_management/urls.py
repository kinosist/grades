from django.urls import path
# 各機能ごとのファイルを個別にインポート
from .views import (
    utils, auth, dashboard, classes, sessions,
    students, quizzes, groups, peer_eval, grades, attendance
)

app_name = 'school_management'

urlpatterns = [
    # --- システム・認証 ---
    path('health/', utils.health_check, name='health_check'),
    path('', auth.login_view, name='login'),
    path('login/', auth.login_view, name='login'),
    # path('debug-login/', auth.debug_login_view, name='debug_login'), # 必要ならauth.pyに追加
    path('logout/', auth.logout_view, name='logout'),

    # --- ダッシュボード ---
    path('dashboard/', dashboard.dashboard_view, name='dashboard'),
    path('student-dashboard/', dashboard.student_dashboard, name='student_dashboard'),
    path('admin-panel/teachers/', dashboard.admin_teacher_management, name='admin_teacher_management'),

    # --- クラス管理 ---
    path('classes/', classes.class_list_view, name='class_list'),
    path('classes/create/', classes.class_create_view, name='class_create'),
    path('classes/<int:class_id>/', classes.class_detail_view, name='class_detail'),
    path('classes/<int:class_id>/delete/', classes.class_delete_view, name='class_delete'),
    
    # --- 成績・評価（Grades） ---
    path('classes/<int:class_id>/points/', grades.class_points_view, name='class_points'),
    path('classes/<int:class_id>/evaluation/', grades.class_evaluation_view, name='class_evaluation'),
    path('classes/<int:class_id>/attendance-rate/', grades.update_attendance_rate, name='update_attendance_rate'),

    # --- クラスへの学生追加・詳細 ---
    path('classes/<int:class_id>/students/select/', students.bulk_student_add, name='class_student_select'),
    path('classes/<int:class_id>/students/bulk-csv/', students.bulk_student_add_csv, name='bulk_student_add'),
    path('classes/<int:class_id>/students/<str:student_number>/', students.class_student_detail_view, name='class_student_detail'),

    # --- 授業セッション（Sessions） ---
    path('classes/<int:class_id>/sessions/', sessions.session_list_view, name='session_list'),
    path('classes/<int:class_id>/sessions/create/', sessions.session_create_view, name='session_create'),
    path('sessions/<int:session_id>/', sessions.session_detail_view, name='session_detail'),
    # 新しい授業作成機能
    path('classes/<int:class_id>/lesson-sessions/create/', sessions.lesson_session_create, name='lesson_session_create'),
    path('lesson-sessions/<int:session_id>/', sessions.lesson_session_detail, name='lesson_session_detail'),

    # --- 小テスト（Quizzes） ---
    path('sessions/<int:session_id>/quizzes/', quizzes.quiz_list_view, name='quiz_list'),
    path('sessions/<int:session_id>/quizzes/create/', quizzes.quiz_create_view, name='quiz_create'),
    path('quizzes/<int:quiz_id>/', quizzes.quiz_results_view, name='quiz_detail'),
    path('quizzes/<int:quiz_id>/grading/', quizzes.quiz_grading_view, name='quiz_grading'),
    path('quizzes/<int:quiz_id>/results/', quizzes.quiz_results_view, name='quiz_results'),
    path('quizzes/<int:quiz_id>/questions/', quizzes.question_manage_view, name='question_manage'),
    path('quizzes/<int:quiz_id>/questions/create/', quizzes.question_create_view, name='question_create'),

    # --- 学生管理（Students） ---
    path('students/', students.student_list_view, name='student_list'),
    path('students/create/', students.student_create_view, name='student_create'),
    path('students/<str:student_number>/', students.student_detail_view, name='student_detail'),
    path('students/<str:student_number>/edit/', students.student_edit_view, name='student_edit'),
    path('student/<int:student_id>/update-points/', students.update_student_points, name='update_student_points'),
    path('student/<int:student_id>/remove-from-class/', students.remove_student_from_class, name='remove_student_from_class'),

    # --- グループ管理（Groups） ---
    path('lesson-sessions/<int:session_id>/groups/', groups.group_list_view, name='group_list'),
    path('lesson-sessions/<int:session_id>/groups/create/', groups.group_management, name='group_management'),
    path('lesson-sessions/<int:session_id>/groups/add/', groups.group_add_view, name='group_add'),
    path('lesson-sessions/<int:session_id>/groups/<int:group_id>/', groups.group_detail_view, name='group_detail'),
    path('lesson-sessions/<int:session_id>/groups/<int:group_id>/edit/', groups.group_edit_view, name='group_edit'),
    path('lesson-sessions/<int:session_id>/groups/<int:group_id>/delete/', groups.group_delete_view, name='group_delete'),
    path('lesson-sessions/<int:session_id>/groups/copy-master/', groups.group_master_copy_to_session, name='group_master_copy'),

    # --- グループマスタ（Group Masters） ---
    path('classes/<int:class_id>/group-masters/', groups.group_master_list_view, name='group_master_list'),
    path('classes/<int:class_id>/group-masters/manage/', groups.group_master_management, name='group_master_management'),

    # --- ピア評価（Peer Eval） ---
    # 改善版（Improved）
    path('lesson-sessions/<int:session_id>/peer-evaluation-improved/create/', peer_eval.improved_peer_evaluation_create, name='improved_peer_evaluation_create'),
    path('lesson-sessions/<int:session_id>/peer-evaluation-improved/links/', peer_eval.peer_evaluation_links, name='peer_evaluation_links'),
    path('lesson-sessions/<int:session_id>/peer-evaluation/', peer_eval.peer_evaluation_common_form, name='peer_evaluation_common'),
    path('lesson-sessions/<int:session_id>/peer-evaluation/close/', peer_eval.close_peer_evaluation, name='close_peer_evaluation'),
    path('lesson-sessions/<int:session_id>/peer-evaluation/reopen/', peer_eval.reopen_peer_evaluation, name='reopen_peer_evaluation'),
    path('lesson-sessions/<int:session_id>/peer-evaluation/results/', peer_eval.peer_evaluation_results, name='peer_evaluation_results'),
    
    # 従来版（Original）
    path('sessions/<int:session_id>/peer-evaluation/', peer_eval.peer_evaluation_list_view, name='peer_evaluation_list'),
    path('sessions/<int:session_id>/peer-evaluation/create/', peer_eval.peer_evaluation_create_view, name='peer_evaluation_create'),
    path('sessions/<int:session_id>/peer-evaluation/link/', peer_eval.peer_evaluation_link_view, name='peer_evaluation_link'),
    path('sessions/<int:session_id>/peer-evaluation/results/', peer_eval.peer_evaluation_results_view, name='peer_evaluation_results'),

    # 回答フォーム（公開・学生用）
    path('peer-evaluation/<str:token>/', peer_eval.peer_evaluation_form_view, name='peer_evaluation_form'),
    path('improved-peer-evaluation/<str:token>/', peer_eval.improved_peer_evaluation_form, name='improved_peer_evaluation_form'),

    # --- QRコード（Attendance） ---
    path('qr-codes/', attendance.qr_code_list, name='qr_code_list'),
    path('qr-codes/student/<int:student_id>/', attendance.qr_code_detail, name='qr_code_detail'),
    path('qr-codes/scan/<uuid:qr_code_id>/', attendance.qr_code_scan, name='qr_code_scan'),
    path('my-qr-code/', attendance.student_qr_code_view, name='student_qr_code'),
    path('classes/<int:class_id>/qr-codes/', attendance.class_qr_codes, name='class_qr_codes'),
]