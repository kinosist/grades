from django.urls import path
from . import views

app_name = 'school_management'

urlpatterns = [
    path('', views.login_view, name='login'),
    path('login/', views.login_view, name='login'),
    path('debug-login/', views.debug_login_view, name='debug_login'),  # デバッグ用
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('student-dashboard/', views.student_dashboard, name='student_dashboard'),
    
    # 管理者用ページ
    path('admin-panel/teachers/', views.admin_teacher_management, name='admin_teacher_management'),
    
    # クラス管理
    path('classes/', views.class_list_view, name='class_list'),
    path('classes/<int:class_id>/', views.class_detail_view, name='class_detail'),
    path('classes/<int:class_id>/points/', views.class_points_view, name='class_points'),
    path('classes/<int:class_id>/evaluation/', views.class_evaluation_view, name='class_evaluation'),
    path('classes/<int:class_id>/attendance-rate/', views.update_attendance_rate, name='update_attendance_rate'),
    path('classes/create/', views.class_create_view, name='class_create'),
    
    # 学生追加（新方式） - より具体的なパターンを先に配置
    path('classes/<int:class_id>/students/select/', views.bulk_student_add, name='class_student_select'),
    path('classes/<int:class_id>/students/bulk-csv/', views.bulk_student_add_csv, name='bulk_student_add'),
    
    # クラス学生詳細 - より汎用的なパターンを後に配置
    path('classes/<int:class_id>/students/<str:student_number>/', views.class_student_detail_view, name='class_student_detail'),
    
    # セッション（授業回）管理
    path('classes/<int:class_id>/sessions/', views.session_list_view, name='session_list'),
    path('classes/<int:class_id>/sessions/create/', views.session_create_view, name='session_create'),
    path('sessions/<int:session_id>/', views.session_detail_view, name='session_detail'),
    
    # 小テスト管理
    path('sessions/<int:session_id>/quizzes/', views.quiz_list_view, name='quiz_list'),
    path('sessions/<int:session_id>/quizzes/create/', views.quiz_create_view, name='quiz_create'),
    path('quizzes/<int:quiz_id>/', views.quiz_results_view, name='quiz_detail'),
    path('quizzes/<int:quiz_id>/grading/', views.quiz_grading_view, name='quiz_grading'),
    path('quizzes/<int:quiz_id>/results/', views.quiz_results_view, name='quiz_results'),
    path('quizzes/<int:quiz_id>/questions/', views.question_manage_view, name='question_manage'),
    path('quizzes/<int:quiz_id>/questions/create/', views.question_create_view, name='question_create'),
    
    # 学生管理
    path('students/', views.student_list_view, name='student_list'),
    path('students/create/', views.student_create_view, name='student_create'),
    path('students/<str:student_number>/', views.student_detail_view, name='student_detail'),
    path('students/<str:student_number>/edit/', views.student_edit_view, name='student_edit'),
    path('student/<int:student_id>/update-points/', views.update_student_points, name='update_student_points'),
    path('student/<int:student_id>/remove-from-class/', views.remove_student_from_class, name='remove_student_from_class'),
    
    # 授業セッション管理
    path('classes/<int:class_id>/lesson-sessions/create/', views.lesson_session_create, name='lesson_session_create'),
    path('lesson-sessions/<int:session_id>/', views.lesson_session_detail, name='lesson_session_detail'),
    
    # グループ管理
    path('lesson-sessions/<int:session_id>/groups/', views.group_list_view, name='group_list'),
    path('lesson-sessions/<int:session_id>/groups/create/', views.group_management, name='group_management'),
    path('lesson-sessions/<int:session_id>/groups/<int:group_id>/', views.group_detail_view, name='group_detail'),
    path('lesson-sessions/<int:session_id>/groups/<int:group_id>/edit/', views.group_edit_view, name='group_edit'),
    path('lesson-sessions/<int:session_id>/groups/<int:group_id>/delete/', views.group_delete_view, name='group_delete'),
    
    # 改善されたピア評価管理
    path('lesson-sessions/<int:session_id>/peer-evaluation-improved/create/', views.improved_peer_evaluation_create, name='improved_peer_evaluation_create'),
    path('lesson-sessions/<int:session_id>/peer-evaluation-improved/links/', views.peer_evaluation_links, name='peer_evaluation_links'),
    
    # 共通ピア評価フォーム
    path('lesson-sessions/<int:session_id>/peer-evaluation/', views.peer_evaluation_common_form, name='peer_evaluation_common'),
    path('lesson-sessions/<int:session_id>/peer-evaluation/close/', views.close_peer_evaluation, name='close_peer_evaluation'),
    path('lesson-sessions/<int:session_id>/peer-evaluation/reopen/', views.reopen_peer_evaluation, name='reopen_peer_evaluation'),
    path('lesson-sessions/<int:session_id>/peer-evaluation/results/', views.peer_evaluation_results, name='peer_evaluation_results'),
    
    # ピア評価管理
    path('sessions/<int:session_id>/peer-evaluation/', views.peer_evaluation_list_view, name='peer_evaluation_list'),
    path('sessions/<int:session_id>/peer-evaluation/create/', views.peer_evaluation_create_view, name='peer_evaluation_create'),
    path('sessions/<int:session_id>/peer-evaluation/link/', views.peer_evaluation_link_view, name='peer_evaluation_link'),
    path('sessions/<int:session_id>/peer-evaluation/results/', views.peer_evaluation_results_view, name='peer_evaluation_results'),
    
    # 学生用匿名ピア評価フォーム
    path('peer-evaluation/<str:token>/', views.peer_evaluation_form_view, name='peer_evaluation_form'),
    path('improved-peer-evaluation/<str:token>/', views.improved_peer_evaluation_form, name='improved_peer_evaluation_form'),
    
    # QRコード関連
    path('qr-codes/', views.qr_code_list, name='qr_code_list'),
    path('qr-codes/student/<int:student_id>/', views.qr_code_detail, name='qr_code_detail'),
    path('qr-codes/scan/<uuid:qr_code_id>/', views.qr_code_scan, name='qr_code_scan'),
    path('my-qr-code/', views.student_qr_code_view, name='student_qr_code'),
    path('classes/<int:class_id>/qr-codes/', views.class_qr_codes, name='class_qr_codes'),
]
