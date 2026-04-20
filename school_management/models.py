import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum, Q
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver


class CustomUserManager(BaseUserManager):
    """カスタムユーザーマネージャー"""
    def create_user(self, email, full_name, password=None, **extra_fields):
        if email:
            email = self.normalize_email(email)
        else:
            email = None
        
        user = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, full_name, password, **extra_fields)


class CustomUser(AbstractUser):
    """統合ユーザーモデル（教員・学生共通）"""
    ROLE_CHOICES = [
        ('admin', '管理者'),
        ('teacher', '教員'),
        ('student', '学生'),
    ]
    
    username = None  # usernameフィールドを無効化
    email = models.EmailField(unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=100, verbose_name='氏名')
    furigana = models.CharField(max_length=100, blank=True, verbose_name='ふりがな')
    points = models.IntegerField(default=0, verbose_name='ポイント')
    role = models.CharField(
        max_length=10, 
        choices=ROLE_CHOICES, 
        default='student',
        verbose_name='役割'
    )
    student_number = models.CharField(max_length=20, blank=True, verbose_name='学籍番号')
    teacher_id = models.CharField(max_length=20, blank=True, verbose_name='教員ID')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='登録日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    # AbstractUserのrelated_nameを設定
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name="customuser_set",
        related_query_name="customuser",
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name="customuser_set",
        related_query_name="customuser",
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']
    
    objects = CustomUserManager()

    class Meta:
        verbose_name = 'ユーザー'
        verbose_name_plural = 'ユーザー'

    def __str__(self):
        return self.full_name

    @property
    def is_teacher(self):
        return self.role in ['teacher', 'admin']
    
    @property
    def is_student(self):
        return self.role == 'student'


# 後方互換性のためのエイリアス
Teacher = CustomUser
Student = CustomUser


class ClassRoom(models.Model):
    """クラス管理"""
    SEMESTER_CHOICES = [
        ('first', '前期'),
        ('second', '後期'),
    ]
    GRADING_SYSTEM_CHOICES = [
        ('default', 'デフォルト（通常）'),
        ('goal', '目標管理（講師評価）'),
        ('original', 'オリジナル（カスタマイズ）'),
    ]
    
    class_name = models.CharField(max_length=100, verbose_name='クラス名')
    year = models.IntegerField(verbose_name='年度')
    semester = models.CharField(max_length=10, choices=SEMESTER_CHOICES, verbose_name='学期')
    grading_system = models.CharField(
        max_length=20, 
        choices=GRADING_SYSTEM_CHOICES, 
        default='default',
        verbose_name='評価システム'
    )
    qr_point_value = models.IntegerField(
        default=1, 
        verbose_name='QRアクションポイント',
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    attendance_max_points = models.IntegerField(
        default=20, 
        verbose_name='出席点満点',
        validators=[MinValueValidator(0), MaxValueValidator(1000)]
    )
    teachers = models.ManyToManyField(Teacher, verbose_name='担当教員', related_name='classrooms')
    students = models.ManyToManyField(Student, blank=True, verbose_name='学生')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'クラス'
        verbose_name_plural = 'クラス'

    def __str__(self):
        return f"{self.year}年 {self.get_semester_display()} {self.class_name}"

    def get_average_points(self):
        """クラスの平均総合ポイントを計算"""
        points_list = self.student_class_points.all()
        count = points_list.count()
        
        if count == 0:
            return 0.0
            
        # 各学生のtotal_pointsプロパティ（出席点 + 授業点*2）の合計を計算
        total_sum = sum(sp.total_points for sp in points_list)
        return round(total_sum / count, 1)


class PointColumn(models.Model):
    """独自の評価項目（列）マスタ"""
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス', related_name='point_columns')
    column_title = models.CharField(max_length=100, verbose_name='項目名')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = '評価項目(列)'
        verbose_name_plural = '評価項目(列)'
        
    def __str__(self):
        return f"{self.classroom.class_name} - {self.column_title}"


#  新規追加：学生ごとの独自項目の「得点」を保存するテーブル
class StudentColumnScore(models.Model):
    """独自評価項目に対する学生の得点データ"""
    column = models.ForeignKey(PointColumn, on_delete=models.CASCADE, verbose_name='評価項目(列)', related_name='scores')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='column_scores')
    score = models.IntegerField(default=0, verbose_name='得点')

    class Meta:
        verbose_name = '独自評価項目の得点'
        verbose_name_plural = '独自評価項目の得点'
        unique_together = ['column', 'student']

    def __str__(self):
        return f"{self.student.full_name} - {self.column.column_title}: {self.score}pt"


class LessonSession(models.Model):
    """授業回マスタ"""
    
    class PeerEvaluationStatus(models.TextChoices):
        NOT_OPEN = 'NOT_OPEN', '受付前'
        OPEN = 'OPEN', '受付中'
        CLOSED = 'CLOSED', '締切'
    
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス')
    session_number = models.IntegerField(verbose_name='回数')
    date = models.DateField(verbose_name='実施日')
    topic = models.CharField(max_length=200, blank=True, verbose_name='テーマ・内容')
    has_quiz = models.BooleanField(default=False, verbose_name='小テストあり')
    has_peer_evaluation = models.BooleanField(default=False, verbose_name='ピア評価あり')
    peer_evaluation_status = models.CharField(
        max_length=10,
        choices=PeerEvaluationStatus.choices,
        default=PeerEvaluationStatus.NOT_OPEN,
        verbose_name='ピア評価ステータス'
    )
    enable_comments = models.BooleanField(default=False, verbose_name='コメント機能有効')
    enable_feedback = models.BooleanField(default=False, verbose_name='感想欄有効')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '授業回'
        verbose_name_plural = '授業回'
        unique_together = ['classroom', 'session_number']

    def __str__(self):
        return f"{self.classroom.class_name} 第{self.session_number}回"
    
    @property
    def peer_evaluation_configured(self):
        """ピア評価設定が存在するかどうか"""
        return hasattr(self, 'peer_evaluation_settings') and self.peer_evaluation_settings is not None
    
    @property
    def peer_evaluation_closed(self):
        """後方互換性: 締切済みかどうか"""
        return self.peer_evaluation_status == self.PeerEvaluationStatus.CLOSED


class PeerEvaluationSettings(models.Model):
    """ピア評価設定（授業回ごと）"""
    
    class ReasonMode(models.TextChoices):
        REQUIRED = 'REQUIRED', '必須'
        OPTIONAL = 'OPTIONAL', '任意'
        DISABLED = 'DISABLED', '無効'
    
    class EvaluationMethod(models.TextChoices):
        DIRECT = 'DIRECT', '直接付与'
        AGGREGATE = 'AGGREGATE', '集計して付与'
    
    lesson_session = models.OneToOneField(
        LessonSession,
        on_delete=models.CASCADE,
        verbose_name='授業回',
        related_name='peer_evaluation_settings'
    )
    
    # メンバー評価設定
    enable_member_evaluation = models.BooleanField(default=False, verbose_name='メンバー評価有効')
    member_scores = models.JSONField(
        default=list, blank=True, verbose_name='メンバー評価配点',
        help_text='例: [5, 3, 1] → 1位5点, 2位3点, 3位1点'
    )
    member_reason_control = models.CharField(
        max_length=20,
        choices=ReasonMode.choices,
        default=ReasonMode.DISABLED,
        verbose_name='メンバー評価理由記入'
    )
    evaluation_method = models.CharField(
        max_length=20,
        choices=EvaluationMethod.choices,
        default=EvaluationMethod.DIRECT,
        verbose_name='メンバー評価の付与方法'
    )
    
    # グループ評価設定
    enable_group_evaluation = models.BooleanField(default=False, verbose_name='グループ評価有効')
    group_scores = models.JSONField(
        default=list, blank=True, verbose_name='グループ評価配点',
        help_text='例: [3, 2] → 1位3点, 2位2点'
    )
    group_reason_control = models.CharField(
        max_length=20,
        choices=ReasonMode.choices,
        default=ReasonMode.DISABLED,
        verbose_name='グループ評価理由記入'
    )
    group_evaluation_method = models.CharField(
        max_length=20,
        choices=EvaluationMethod.choices,
        default=EvaluationMethod.DIRECT,
        verbose_name='グループ評価の付与方法'
    )
    
    # 表示設定
    show_points = models.BooleanField(default=True, verbose_name='配点テーブルを表示')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'ピア評価設定'
        verbose_name_plural = 'ピア評価設定'
    
    def __str__(self):
        return f"{self.lesson_session} ピア評価設定"

    @staticmethod
    def _normalize_scores(values):
        if not isinstance(values, list):
            return []
        normalized = []
        for value in values:
            try:
                normalized.append(max(0, int(value)))
            except (TypeError, ValueError):
                continue
        return normalized

    def clean(self):
        self.member_scores = self._normalize_scores(self.member_scores)
        self.group_scores = self._normalize_scores(self.group_scores)

        if not self.enable_member_evaluation:
            self.member_scores = []
            self.member_reason_control = self.ReasonMode.DISABLED
        if not self.enable_group_evaluation:
            self.group_scores = []
            self.group_reason_control = self.ReasonMode.DISABLED
            self.group_evaluation_method = self.EvaluationMethod.DIRECT

        session_status = self.lesson_session.peer_evaluation_status
        if session_status != LessonSession.PeerEvaluationStatus.NOT_OPEN:
            if not self.pk:
                raise ValidationError('受付開始後のピア評価設定は作成できません。')

            old = PeerEvaluationSettings.objects.get(pk=self.pk)
            immutable_fields = (
                'enable_member_evaluation',
                'member_scores',
                'member_reason_control',
                'evaluation_method',
                'enable_group_evaluation',
                'group_scores',
                'group_reason_control',
                'group_evaluation_method',
                'show_points',
            )
            for field in immutable_fields:
                if getattr(self, field) != getattr(old, field):
                    raise ValidationError('受付開始後のピア評価設定は変更できません。')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    @property
    def member_ranking_count(self):
        """メンバー評価の順位数"""
        return len(self.member_scores) if self.member_scores else 0
    
    @property
    def group_ranking_count(self):
        """グループ評価の順位数"""
        return len(self.group_scores) if self.group_scores else 0


class Group(models.Model):
    """グループ"""
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    group_number = models.IntegerField(verbose_name='グループ番号')
    group_name = models.CharField(max_length=100, blank=True, verbose_name='グループ名', help_text='例: チーム虎、開発班A、など')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'グループ'
        verbose_name_plural = 'グループ'
        unique_together = ['lesson_session', 'group_number']

    def __str__(self):
        if self.group_name:
            return f"{self.lesson_session} {self.group_name}({self.group_number}グループ)"
        return f"{self.lesson_session} グループ{self.group_number}"

    @property
    def display_name(self):
        """表示用の名前を返す"""
        if self.group_name:
            return f"{self.group_name}"
        return f"{self.group_number}グループ"


class GroupMember(models.Model):
    """グループメンバー"""
    group = models.ForeignKey(Group, on_delete=models.CASCADE, verbose_name='グループ')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='group_memberships')
    role = models.CharField(max_length=50, blank=True, verbose_name='役割')

    class Meta:
        verbose_name = 'グループメンバー'
        verbose_name_plural = 'グループメンバー'
        unique_together = ['group', 'student']

    def __str__(self):
        return f"{self.group} - {self.student.full_name}"


class GroupMaster(models.Model):
    """グループマスタ（クラスごとの固定グループ）"""
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス', related_name='group_masters')
    group_number = models.IntegerField(verbose_name='グループ番号')
    group_name = models.CharField(max_length=100, blank=True, verbose_name='グループ名', help_text='例: チーム虎、開発班A、など')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'グループマスタ'
        verbose_name_plural = 'グループマスタ'
        unique_together = ['classroom', 'group_number']

    def __str__(self):
        if self.group_name:
            return f"{self.classroom} {self.group_name}({self.group_number}グループ)"
        return f"{self.classroom} グループ{self.group_number}"

    @property
    def display_name(self):
        """表示用の名前を返す"""
        if self.group_name:
            return f"{self.group_name}"
        return f"{self.group_number}グループ"


class GroupMasterMember(models.Model):
    """グループマスタメンバー"""
    group_master = models.ForeignKey(GroupMaster, on_delete=models.CASCADE, verbose_name='グループマスタ', related_name='members')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='group_master_memberships')
    role = models.CharField(max_length=50, blank=True, verbose_name='役割')

    class Meta:
        verbose_name = 'グループマスタメンバー'
        verbose_name_plural = 'グループマスタメンバー'
        unique_together = ['group_master', 'student']

    def __str__(self):
        return f"{self.group_master} - {self.student.full_name}"


class Quiz(models.Model):
    """小テスト"""
    GRADING_METHOD_CHOICES = [
        ('pass_fail', '合否'),
        ('numeric', '数値入力'),
        ('rubric', 'ルーブリック'),
        ('qr_mobile', 'QRコード巡回採点'),
    ]
    
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    quiz_name = models.CharField(max_length=100, verbose_name='小テスト名')
    max_score = models.IntegerField(verbose_name='満点')
    grading_method = models.CharField(
        max_length=20, 
        choices=GRADING_METHOD_CHOICES, 
        default='numeric', 
        verbose_name='採点方式'
    )
    quick_buttons = models.JSONField(null=True, blank=True, verbose_name='クイックボタン設定')
    is_qr_linked = models.BooleanField(default=False, verbose_name='QR連携')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '小テスト'
        verbose_name_plural = '小テスト'

    def __str__(self):
        return f"{self.lesson_session} - {self.quiz_name}"

    def get_student_scores(self):
        """クラスの全学生のスコアリストを返す（学籍番号順）"""
        # クラスの全学生を取得
        students = self.lesson_session.classroom.students.all().order_by('student_number')
        # 既存のスコアを取得（キャンセルされたものは除外）
        scores = {qs.student_id: qs.score for qs in self.quizscore_set.filter(is_cancelled=False)}
        
        results = []
        for student in students:
            results.append({
                'student': student,
                'score': scores.get(student.id, 0),
                'has_score': student.id in scores
            })
        return results


class QuizScore(models.Model):
    """小テスト採点結果"""
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, verbose_name='小テスト')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='quiz_scores_as_student')
    score = models.IntegerField(verbose_name='得点')
    graded_by = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name='採点者', related_name='quiz_scores_graded')
    is_cancelled = models.BooleanField(default=False, verbose_name='取り消し済み')
    graded_at = models.DateTimeField(auto_now_add=True, verbose_name='採点日時')

    class Meta:
        verbose_name = '小テスト結果'
        verbose_name_plural = '小テスト結果'

    def __str__(self):
        return f"{self.quiz} - {self.student.full_name}: {self.score}点"

    @property
    def percentage(self):
        """正答率を計算"""
        if self.quiz.max_score > 0:
            return (self.score / self.quiz.max_score) * 100
        return 0

class Question(models.Model):
    """小テストの問題"""
    QUESTION_TYPE_CHOICES = [
        ('multiple_choice', '選択問題'),
        ('true_false', '正誤問題'),
        ('short_answer', '記述問題'),
    ]
    
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, verbose_name='小テスト', related_name='questions')
    question_text = models.TextField(verbose_name='問題文')
    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPE_CHOICES,
        default='multiple_choice',
        verbose_name='問題形式'
    )
    points = models.IntegerField(default=1, verbose_name='配点')
    order = models.IntegerField(default=1, verbose_name='出題順')
    correct_answer = models.TextField(blank=True, verbose_name='正解（記述問題用）')
    
    class Meta:
        verbose_name = '問題'
        verbose_name_plural = '問題'
        ordering = ['order']
    
    def __str__(self):
        return f"{self.quiz.quiz_name} - 問題{self.order}"


class QuestionChoice(models.Model):
    """問題の選択肢"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, verbose_name='問題', related_name='choices')
    choice_text = models.CharField(max_length=500, verbose_name='選択肢')
    is_correct = models.BooleanField(default=False, verbose_name='正解')
    order = models.IntegerField(default=1, verbose_name='表示順')
    
    class Meta:
        verbose_name = '選択肢'
        verbose_name_plural = '選択肢'
        ordering = ['order']
    
    def __str__(self):
        return f"{self.question} - {self.choice_text}"


class PeerEvaluation(models.Model):
    """ピア評価"""
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    student = models.ForeignKey(
        Student,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='peer_evaluations',
        verbose_name='提出学生'
    )
    email = models.EmailField(blank=True, default='', verbose_name='提出メールアドレス')
    evaluator_token = models.UUIDField(verbose_name='評価者トークン（匿名化）')
    evaluator_group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='peer_evaluations_as_evaluator',
        verbose_name='評価者グループ'
    )
    evaluator_group_number = models.IntegerField(verbose_name='評価者グループ番号', null=True, blank=True)
    
    # 評価データ（JSON形式）
    response_json = models.JSONField(
        default=dict, blank=True, verbose_name='評価データ',
        help_text='{"group_members_eval": [...], "other_group_eval": [...]}'
    )
    
    class_comment = models.TextField(blank=True, verbose_name='授業コメント')
    general_comment = models.TextField(blank=True, verbose_name='全般コメント')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='評価日時')

    class Meta:
        verbose_name = 'ピア評価'
        verbose_name_plural = 'ピア評価'
        constraints = [
            models.UniqueConstraint(
                fields=['lesson_session', 'student'],
                condition=Q(student__isnull=False),
                name='unique_peer_eval_per_student_per_session',
            ),
        ]

    def __str__(self):
        return f"{self.lesson_session} - 匿名評価 ({self.created_at.strftime('%m/%d %H:%M')})"

    def save(self, *args, **kwargs):
        if self.evaluator_group:
            self.evaluator_group_number = self.evaluator_group.group_number
        super().save(*args, **kwargs)


class ContributionEvaluation(models.Model):
    """貢献度評価"""
    peer_evaluation = models.ForeignKey(PeerEvaluation, on_delete=models.CASCADE, verbose_name='ピア評価')
    evaluatee = models.ForeignKey(
        Student, 
        on_delete=models.CASCADE, 
        related_name='contributioneval_evaluatee',
        verbose_name='被評価者'
    )
    contribution_score = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='貢献度スコア'
    )

    class Meta:
        verbose_name = '貢献度評価'
        verbose_name_plural = '貢献度評価'
        unique_together = ['peer_evaluation', 'evaluatee']

    def __str__(self):
        return f"{self.peer_evaluation} - {self.evaluatee.full_name}: {self.contribution_score}点"


class GoogleOAuthSession(models.Model):
    """Google OAuth認証済みセッション（匿名フォーム向け）"""
    session_id = models.CharField(max_length=128, unique=True, verbose_name='セッションID')
    email = models.EmailField(verbose_name='認証メールアドレス')
    expires_at = models.DateTimeField(db_index=True, verbose_name='有効期限')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    class Meta:
        verbose_name = 'Google OAuthセッション'
        verbose_name_plural = 'Google OAuthセッション'

    def __str__(self):
        return f"{self.email} ({self.expires_at:%Y-%m-%d %H:%M})"


class Attendance(models.Model):
    """出席情報"""
    ATTENDANCE_STATUS_CHOICES = [
        ('present', '出席'),
        ('absent', '欠席'),
        ('late', '遅刻'),
        ('early_leave', '早退'),
    ]
    
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='attendances')
    status = models.CharField(
        max_length=20,
        choices=ATTENDANCE_STATUS_CHOICES,
        default='present',
        verbose_name='出席状況'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = '出席情報'
        verbose_name_plural = '出席情報'
        unique_together = ['lesson_session', 'student']
    
    def __str__(self):
        return f"{self.lesson_session} - {self.student.full_name}: {self.get_status_display()}"


class StudentQRCode(models.Model):
    """学生QRコード"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='qr_codes')
    qr_code_id = models.UUIDField(default=uuid.uuid4, unique=True, verbose_name='QRコードID')
    is_active = models.BooleanField(default=True, verbose_name='有効')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name='最終使用日時')
    
    class Meta:
        verbose_name = '学生QRコード'
        verbose_name_plural = '学生QRコード'
    
    def __str__(self):
        return f"{self.student.full_name}のQRコード"
    
    @property
    def qr_code_url(self):
        """QRコードのURLを生成"""
        from django.urls import reverse
        return reverse('qr_code_scan', kwargs={'qr_code_id': self.qr_code_id})


class QRCodeScan(models.Model):
    """QRコードスキャン履歴"""
    qr_code = models.ForeignKey(StudentQRCode, on_delete=models.CASCADE, verbose_name='QRコード', related_name='scans')
    scanned_by = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='スキャン者', related_name='qr_scans')
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業セッション', related_name='qr_scans', null=True, blank=True)
    point_column = models.ForeignKey(PointColumn, on_delete=models.CASCADE, verbose_name='独自評価項目', related_name='qr_scans', null=True, blank=True)
    points_awarded = models.IntegerField(default=1, verbose_name='付与ポイント')
    scanned_at = models.DateTimeField(auto_now_add=True, verbose_name='スキャン日時')
    
    class Meta:
        verbose_name = 'QRコードスキャン'
        verbose_name_plural = 'QRコードスキャン'
        # unique_together制約を削除 - 何度でもスキャン可能にする
    
    def __str__(self):
        return f"{self.qr_code.student.full_name}のQRコードを{self.scanned_by.full_name}がスキャン"


class StudentLessonPoints(models.Model):
    """学生の授業ごとのポイント管理"""
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name='学生', related_name='lesson_points')
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業セッション', related_name='student_points')
    points = models.IntegerField(default=0, verbose_name='ポイント')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')
    
    class Meta:
        verbose_name = '学生授業ポイント'
        verbose_name_plural = '学生授業ポイント'
        unique_together = ['student', 'lesson_session']  # 同じ学生の同じ授業セッションは1つのレコードのみ
    
    def __str__(self):
        return f"{self.student.full_name} - {self.lesson_session.classroom.class_name} 第{self.lesson_session.session_number}回 ({self.lesson_session.date}) - {self.points}pt"


class StudentClassPoints(models.Model):
    """学生ごとのクラス単位のポイント管理"""
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name='学生', related_name='class_points')
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス', related_name='student_class_points')
    points = models.IntegerField(default=0, verbose_name='ポイント')
    attendance_rate = models.FloatField(default=0.0, verbose_name='出席率', help_text='0-100の範囲')
    attendance_points = models.FloatField(default=0.0, verbose_name='出席点', help_text='出席率から計算される点数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    class Meta:
        verbose_name = '学生クラスポイント'
        verbose_name_plural = '学生クラスポイント'
        unique_together = ['student', 'classroom']

    def __str__(self):
        return f"{self.student.full_name} - {self.classroom.class_name} - {self.points}pt"

    def calculate_points_internal(self):
        """内部計算用: 各種スコアを集計してpointsフィールドを更新する"""
        # 目標管理モードの場合
        if self.classroom.grading_system == 'goal':
            # 遅延インポートで循環参照を回避
            from django.apps import apps
            SelfEvaluation = apps.get_model('school_management', 'SelfEvaluation')
            self_eval = SelfEvaluation.objects.filter(student=self.student, classroom=self.classroom).first()
            
            # 講師評価点を取得（なければ0）
            teacher_score = 0
            if self_eval and self_eval.teacher_score is not None:
                teacher_score = self_eval.teacher_score
            
            # 合計 = 講師評価点 + 出席点
            self.points = int(teacher_score + self.attendance_points)
            return

        # 小テストの合計
        # 重複データ対策: 同一クイズのスコアが複数ある場合は最新のみ採用
        all_quiz_scores = QuizScore.objects.filter(
            student=self.student,
            quiz__lesson_session__classroom=self.classroom,
            is_cancelled=False
        ).order_by('graded_at')
        
        # 辞書で上書きすることで最新のスコアのみを残す
        quiz_total = sum({qs.quiz_id: qs.score for qs in all_quiz_scores}.values())
        
        # 授業ポイントの合計
        lesson_total = StudentLessonPoints.objects.filter(
            student=self.student,
            lesson_session__classroom=self.classroom
        ).aggregate(total=Sum('points'))['total'] or 0
        
        # ピア評価ポイント (貢献度 + グループ投票)
        peer_total = 0
        
        # 1. 貢献度評価 (5段階評価の合計)
        contrib_evals = ContributionEvaluation.objects.filter(
            evaluatee=self.student,
            peer_evaluation__lesson_session__classroom=self.classroom
        )
        peer_total += contrib_evals.aggregate(total=Sum('contribution_score'))['total'] or 0
        
        # 2. グループ投票ポイント（response_jsonベース）
        peer_total += self._calculate_group_vote_points()
                
        #  新規追加: 独自評価項目（列）の合計得点を計算
        custom_columns_total = StudentColumnScore.objects.filter(
            student=self.student,
            column__classroom=self.classroom
        ).aggregate(total=Sum('score'))['total'] or 0

        # 合計を計算
        # 式: (小テスト(QR含む) + ピア評価 + 授業内ポイント + 独自評価項目) * 倍率(2) + 出席点
        class_only_points = quiz_total + peer_total + lesson_total + custom_columns_total
        self.points = int((class_only_points * 2) + self.attendance_points)

    @property
    def quiz_stats(self):
        """重複を除外したクイズ統計を返す（回数と平均点）"""
        all_quiz_scores = QuizScore.objects.filter(
            student=self.student,
            quiz__lesson_session__classroom=self.classroom,
            is_cancelled=False
        ).order_by('graded_at')
        
        # 辞書で上書きすることで最新のスコアのみを残す（重複対策）
        unique_scores = {qs.quiz_id: qs.score for qs in all_quiz_scores}
        
        count = len(unique_scores)
        total = sum(unique_scores.values())
        avg = round(total / count, 1) if count > 0 else 0
        
        return {'count': count, 'average': avg}

    @property
    def live_points(self):
        """表示用にリアルタイムで再計算した値を返す（DB保存はしない）"""
        self.calculate_points_internal()
        return self.points

    def _calculate_group_vote_points(self):
        """response_jsonベースでグループ投票ポイントを計算"""
        student_groups = list(GroupMember.objects.filter(
            student=self.student,
            group__lesson_session__classroom=self.classroom
        ).select_related('group__lesson_session'))
        if not student_groups:
            return 0

        session_settings = {}
        target_session_ids = set()
        for membership in student_groups:
            session = membership.group.lesson_session
            if session.id in session_settings:
                continue
            try:
                pe_settings = session.peer_evaluation_settings
            except PeerEvaluationSettings.DoesNotExist:
                session_settings[session.id] = None
                continue

            score_points = pe_settings.group_scores or []
            if not pe_settings.enable_group_evaluation or not score_points:
                session_settings[session.id] = None
                continue

            session_settings[session.id] = {
                'method': pe_settings.group_evaluation_method,
                'score_points': score_points,
                'peer_status': session.peer_evaluation_status,
            }
            target_session_ids.add(session.id)

        if not target_session_ids:
            return 0

        session_groups = {}
        for group in Group.objects.filter(lesson_session_id__in=target_session_ids).values('id', 'lesson_session_id'):
            session_groups.setdefault(group['lesson_session_id'], []).append(group['id'])

        session_eval_responses = {}
        eval_rows = PeerEvaluation.objects.filter(
            lesson_session_id__in=target_session_ids
        ).values_list('lesson_session_id', 'response_json')
        for session_id, response_json in eval_rows:
            session_eval_responses.setdefault(session_id, []).append(response_json or {})

        session_group_point_maps = {}
        for session_id in target_session_ids:
            settings = session_settings.get(session_id)
            group_ids = session_groups.get(session_id, [])
            group_point_map = {group_id: 0 for group_id in group_ids}

            if not settings or not group_ids:
                session_group_point_maps[session_id] = group_point_map
                continue

            score_points = settings['score_points']
            eval_responses = session_eval_responses.get(session_id, [])

            if settings['method'] == PeerEvaluationSettings.EvaluationMethod.AGGREGATE:
                if settings['peer_status'] == LessonSession.PeerEvaluationStatus.CLOSED:
                    # 締切時に内部ポイント(G-N)で集計し、順位配点を付与
                    group_internal_points = {group_id: 0 for group_id in group_ids}
                    group_count = len(group_ids)
                    for response in eval_responses:
                        for entry in response.get('other_group_eval', []):
                            gid = entry.get('group_id')
                            rank = entry.get('rank')
                            if gid in group_internal_points and rank and 1 <= rank <= group_count:
                                group_internal_points[gid] += (group_count - rank)

                    sorted_groups = sorted(
                        group_internal_points.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                    current_rank = 0
                    prev_points = None
                    for idx, (gid, internal_points) in enumerate(sorted_groups):
                        if internal_points != prev_points:
                            current_rank = idx
                            prev_points = internal_points
                        if current_rank < len(score_points):
                            group_point_map[gid] = score_points[current_rank]
            else:
                # 直接付与: 各回答の順位配点をそのまま加算
                for response in eval_responses:
                    for entry in response.get('other_group_eval', []):
                        gid = entry.get('group_id')
                        rank = entry.get('rank')
                        if gid and rank and 1 <= rank <= len(score_points):
                            if gid in group_point_map:
                                group_point_map[gid] += score_points[rank - 1]

            session_group_point_maps[session_id] = group_point_map

        vote_total = 0
        for membership in student_groups:
            group = membership.group
            group_point_map = session_group_point_maps.get(group.lesson_session_id, {})
            my_points = group_point_map.get(group.id, 0)
            if my_points > 0:
                vote_total += my_points
        
        return vote_total

    def get_activity_points(self):
        """モードに関係なく、純粋な積み上げポイント（授業点相当）を計算して返す"""
        # 小テスト (重複対策)
        all_quiz_scores = QuizScore.objects.filter(
            student=self.student,
            quiz__lesson_session__classroom=self.classroom,
            is_cancelled=False
        ).order_by('graded_at')
        quiz_total = sum({qs.quiz_id: qs.score for qs in all_quiz_scores}.values())
        
        lesson_total = StudentLessonPoints.objects.filter(
            student=self.student,
            lesson_session__classroom=self.classroom
        ).aggregate(total=Sum('points'))['total'] or 0
        
        # ピア評価
        peer_total = 0
        contrib_evals = ContributionEvaluation.objects.filter(
            evaluatee=self.student,
            peer_evaluation__lesson_session__classroom=self.classroom
        )
        peer_total += contrib_evals.aggregate(total=Sum('contribution_score'))['total'] or 0
        peer_total += self._calculate_group_vote_points()
                
        # 独自評価項目（列）の合計得点を計算
        custom_columns_total = StudentColumnScore.objects.filter(
            student=self.student,
            column__classroom=self.classroom
        ).aggregate(total=Sum('score'))['total'] or 0
        
        return int(quiz_total + lesson_total + peer_total + custom_columns_total)

    @property
    def class_points(self):
        """評価一覧用: モードに応じた授業点を返す"""
        # 目標管理モードの場合はpoints(合計)から出席点を引いた値を返す
        if self.classroom.grading_system == 'goal':
            return max(0, self.points - int(self.attendance_points))
        
        # 通常モードは積み上げ値を返す
        return self.get_activity_points()

    @property
    def total_points(self):
        """評価一覧用: モードに応じた総合ポイントを返す"""
        if self.classroom.grading_system == 'goal':
            return self.points
        # 表示用に、出席点(float)を含めた正確な値を返す
        return (self.get_activity_points() * 2) + self.attendance_points

    @property
    def total_activity_points(self):
        """活動量表示用: モードに関係なく、積み上げポイントに基づいた合計（倍率適用 + 出席点）を返す"""
        return (self.get_activity_points() * 2) + self.attendance_points

    def save(self, *args, **kwargs):
        """保存時に自動的にポイントを再計算する"""
        self.calculate_points_internal()
        super().save(*args, **kwargs)

    def recalculate_total(self):
        """外部呼び出し用互換メソッド（シグナル等から呼ばれる）"""
        self.save()

    def get_peer_history(self):
        """ピア評価の獲得ポイント履歴（貢献度、投票点、合計）を返す"""
        from .models import ContributionEvaluation, GroupMember, PeerEvaluation, Group, PeerEvaluationSettings
        from django.db.models import Sum

        history = []
        sessions = self.classroom.lessonsession_set.filter(has_peer_evaluation=True).order_by('-session_number')
        
        for session in sessions:
            contrib_score = ContributionEvaluation.objects.filter(
                evaluatee=self.student,
                peer_evaluation__lesson_session=session
            ).aggregate(total=Sum('contribution_score'))['total'] or 0
            
            vote_score = 0
            membership = GroupMember.objects.filter(
                student=self.student,
                group__lesson_session=session
            ).first()
            
            if membership:
                group = membership.group
                try:
                    pe_settings = session.peer_evaluation_settings
                except PeerEvaluationSettings.DoesNotExist:
                    pe_settings = None
                
                if pe_settings and pe_settings.enable_group_evaluation:
                    score_points = pe_settings.group_scores or []
                    if score_points:
                        session_groups = list(Group.objects.filter(lesson_session=session))
                        group_point_map = {g.id: 0 for g in session_groups}
                        
                        evals = PeerEvaluation.objects.filter(lesson_session=session)
                        if pe_settings.group_evaluation_method == PeerEvaluationSettings.EvaluationMethod.AGGREGATE:
                            if session.peer_evaluation_status == LessonSession.PeerEvaluationStatus.CLOSED:
                                group_internal_points = {g.id: 0 for g in session_groups}
                                group_count = len(session_groups)
                                for ev in evals:
                                    response = ev.response_json or {}
                                    for entry in response.get('other_group_eval', []):
                                        gid = entry.get('group_id')
                                        rank = entry.get('rank')
                                        if gid in group_internal_points and rank and 1 <= rank <= group_count:
                                            group_internal_points[gid] += (group_count - rank)
                                sorted_groups = sorted(
                                    group_internal_points.items(),
                                    key=lambda x: x[1],
                                    reverse=True,
                                )
                                current_rank = 0
                                prev_points = None
                                for idx, (gid, internal_points) in enumerate(sorted_groups):
                                    if internal_points != prev_points:
                                        current_rank = idx
                                        prev_points = internal_points
                                    if current_rank < len(score_points):
                                        group_point_map[gid] = score_points[current_rank]
                        else:
                            for ev in evals:
                                response = ev.response_json or {}
                                for entry in response.get('other_group_eval', []):
                                    gid = entry.get('group_id')
                                    rank = entry.get('rank')
                                    if gid and rank and 1 <= rank <= len(score_points):
                                        if gid in group_point_map:
                                            group_point_map[gid] += score_points[rank - 1]
                        
                        vote_score = group_point_map.get(group.id, 0)
            
            total_score = contrib_score + vote_score
            if total_score > 0:
                history.append({
                    'session': session,
                    'contrib': contrib_score,
                    'vote': vote_score,
                    'total': total_score
                })
                
        return history[:10]


class StudentGoal(models.Model):
    """学生のクラス目標（学期ごとに先生が設定）"""
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name='学生', related_name='goals')
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス', related_name='student_goals')
    goal_text = models.TextField(verbose_name='目標')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    class Meta:
        verbose_name = '学生目標'
        verbose_name_plural = '学生目標'
        unique_together = ['student', 'classroom']

    def __str__(self):
        return f"{self.student.full_name} - {self.classroom.class_name}: {self.goal_text[:30]}"


class LessonReport(models.Model):
    """授業回ごとの学生日報（先生が入力）"""
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回', related_name='lesson_reports')
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name='学生', related_name='lesson_reports')
    report_text = models.TextField(verbose_name='日報・今日やったこと')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    class Meta:
        verbose_name = '日報'
        verbose_name_plural = '日報'
        unique_together = ['lesson_session', 'student']

    def __str__(self):
        return f"{self.student.full_name} - {self.lesson_session}: {self.report_text[:30]}"


class SelfEvaluation(models.Model):
    """学期末の自己評価・教師評価"""
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name='学生', related_name='self_evaluations')
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス', related_name='self_evaluations')
    # 学生の自己評価
    student_comment = models.TextField(blank=True, verbose_name='学生コメント')
    student_score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name='学生自己評価点'
    )
    # 教師評価
    teacher_comment = models.TextField(blank=True, verbose_name='教師コメント')
    teacher_score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name='教師評価点'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    class Meta:
        verbose_name = '自己評価'
        verbose_name_plural = '自己評価'
        unique_together = ['student', 'classroom']

    def __str__(self):
        return f"{self.student.full_name} - {self.classroom.class_name} 自己評価"


# --- Signals ---
@receiver([post_save, post_delete], sender=QuizScore)
def update_class_points_from_quiz(sender, instance, **kwargs):
    if instance.quiz.lesson_session.classroom:
        try:
            scp = StudentClassPoints.objects.get(
                student=instance.student,
                classroom=instance.quiz.lesson_session.classroom
            )
            scp.recalculate_total()
        except StudentClassPoints.DoesNotExist:
            if kwargs.get('signal') == post_save:
                scp = StudentClassPoints.objects.create(
                    student=instance.student,
                    classroom=instance.quiz.lesson_session.classroom
                )
                scp.recalculate_total()

@receiver([post_save, post_delete], sender=StudentLessonPoints)
def update_class_points_from_lesson(sender, instance, **kwargs):
    if instance.lesson_session.classroom:
        try:
            scp = StudentClassPoints.objects.get(
                student=instance.student,
                classroom=instance.lesson_session.classroom
            )
            scp.recalculate_total()
        except StudentClassPoints.DoesNotExist:
            if kwargs.get('signal') == post_save:
                scp = StudentClassPoints.objects.create(
                    student=instance.student,
                    classroom=instance.lesson_session.classroom
                )
                scp.recalculate_total()

@receiver([post_save, post_delete], sender=SelfEvaluation)
def update_class_points_from_self_eval(sender, instance, **kwargs):
    """自己評価・教師評価更新時に成績を再計算"""
    if instance.classroom:
        try:
            scp = StudentClassPoints.objects.get(
                student=instance.student,
                classroom=instance.classroom
            )
            scp.recalculate_total()
        except StudentClassPoints.DoesNotExist:
            if kwargs.get('signal') == post_save:
                scp = StudentClassPoints.objects.create(
                    student=instance.student,
                    classroom=instance.classroom
                )
                scp.recalculate_total()

@receiver(post_save, sender=LessonSession)
def create_qr_quiz_for_session(sender, instance, created, **kwargs):
    """授業回作成時にQR連携用小テストを自動作成"""
    if created:
        Quiz.objects.create(
            lesson_session=instance,
            quiz_name="QRアクション点",
            max_score=100,
            grading_method='qr_mobile',
            is_qr_linked=True
        )

@receiver([post_save, post_delete], sender=QRCodeScan)
def update_quiz_score_from_qr(sender, instance, **kwargs):
    """QRスキャン履歴の変更時（追加・削除）に小テストの点数を再集計して更新"""
    if not instance.lesson_session:
        return
        
    # 独自評価項目のスキャン履歴の場合は、QuizScoreの集計対象から除外する
    if getattr(instance, 'point_column_id', None) is not None:
        return

    # 連携小テストを探す
    quiz = Quiz.objects.filter(lesson_session=instance.lesson_session, is_qr_linked=True).first()
    
    # クイズがない場合
    if not quiz:
        # 削除時は何もしない（集計先がないため）
        if kwargs.get('signal') == post_delete:
            return
            
        # 作成・更新時は既存を探すか新規作成
        quiz = Quiz.objects.filter(lesson_session=instance.lesson_session).first()
        if quiz:
            quiz.is_qr_linked = True
            quiz.save()
        else:
            quiz = Quiz.objects.create(
                lesson_session=instance.lesson_session,
                quiz_name="QRアクション点",
                max_score=100,
                grading_method='qr_mobile',
                is_qr_linked=True
            )
    
    try:
        student = instance.qr_code.student
    except Exception:
        # 関連オブジェクトが削除されている場合はスキップ
        return

    # 合計ポイントを再集計（集計元をQRCodeScanに一本化）
    total_points = QRCodeScan.objects.filter(
        lesson_session=instance.lesson_session,
        qr_code__student=student,
        point_column__isnull=True
    ).aggregate(total=Sum('points_awarded'))['total'] or 0
    
    # QuizScoreを取得または作成
    scores = QuizScore.objects.filter(quiz=quiz, student=student).order_by('-id')
    
    if scores.exists():
        score_obj = scores.first()
        if scores.count() > 1:
            scores.exclude(id=score_obj.id).delete()
        
        # 点数を更新（変更がある場合のみ保存して再計算シグナルを発火）
        if score_obj.score != total_points:
            score_obj.score = total_points
            score_obj.save()
    elif kwargs.get('signal') == post_save:
        # 削除時以外のみ新規作成（カスケード削除時の復活防止）
        QuizScore.objects.create(
            quiz=quiz,
            student=student,
            score=total_points,
            graded_by=instance.scanned_by
        )

@receiver(pre_save, sender=QRCodeScan)
def set_qr_points_from_class_settings(sender, instance, **kwargs):
    """QRスキャン時にクラス設定のポイント値を適用"""
    if not instance.pk and instance.lesson_session and instance.lesson_session.classroom:
        # 独自項目が指定されている場合、または明示的にポイントが指定されている場合は上書きしない
        if getattr(instance, 'point_column_id', None) is not None or instance.points_awarded != 1:
            return
        instance.points_awarded = instance.lesson_session.classroom.qr_point_value

@receiver(pre_save, sender=PeerEvaluation)
def set_peer_evaluation_group_numbers(sender, instance, **kwargs):
    """ピア評価保存時にグループ番号を自動設定（リンク切れ防止）"""
    if instance.evaluator_group:
        instance.evaluator_group_number = instance.evaluator_group.group_number

@receiver([post_save, post_delete], sender=ContributionEvaluation)
def update_class_points_from_contribution(sender, instance, **kwargs):
    """貢献度評価更新時に成績を再計算"""
    if instance.peer_evaluation.lesson_session.classroom:
        try:
            scp = StudentClassPoints.objects.get(
                student=instance.evaluatee,
                classroom=instance.peer_evaluation.lesson_session.classroom
            )
            scp.recalculate_total()
        except StudentClassPoints.DoesNotExist:
            if kwargs.get('signal') == post_save:
                scp = StudentClassPoints.objects.create(
                    student=instance.evaluatee,
                    classroom=instance.peer_evaluation.lesson_session.classroom
                )
                scp.recalculate_total()

@receiver([post_save, post_delete], sender=PeerEvaluation)
def update_class_points_from_peer_vote(sender, instance, **kwargs):
    """ピア評価（投票）更新時に成績を再計算"""
    try:
        if instance.lesson_session.classroom:
            # response_jsonからグループ評価を取得して再計算
            groups = []
            response = instance.response_json or {}
            other_group_eval = response.get('other_group_eval', [])
            for entry in other_group_eval:
                group_id = entry.get('group_id')
                if group_id:
                    try:
                        g = Group.objects.get(id=group_id, lesson_session=instance.lesson_session)
                        groups.append(g)
                    except Group.DoesNotExist:
                        pass
            
            for group in groups:
                members = GroupMember.objects.filter(group=group)
                for member in members:
                    try:
                        scp = StudentClassPoints.objects.get(
                            student=member.student,
                            classroom=instance.lesson_session.classroom
                        )
                        scp.recalculate_total()
                    except StudentClassPoints.DoesNotExist:
                        if kwargs.get('signal') == post_save:
                            scp = StudentClassPoints.objects.create(
                                student=member.student,
                                classroom=instance.lesson_session.classroom
                            )
                            scp.recalculate_total()
    except Exception:
        pass

@receiver([post_save, post_delete], sender=GroupMember)
def update_class_points_from_group_member(sender, instance, **kwargs):
    """グループメンバー変更時に成績を再計算"""
    try:
        if instance.group.lesson_session.classroom:
            try:
                scp = StudentClassPoints.objects.get(
                    student=instance.student,
                    classroom=instance.group.lesson_session.classroom
                )
                scp.recalculate_total()
            except StudentClassPoints.DoesNotExist:
                if kwargs.get('signal') == post_save:
                    scp = StudentClassPoints.objects.create(
                        student=instance.student,
                        classroom=instance.group.lesson_session.classroom
                    )
                    scp.recalculate_total()
    except Exception:
        pass

#  新規追加：独自評価項目の得点が変わった時も、自動で全体の成績を再計算する設定
@receiver([post_save, post_delete], sender=StudentColumnScore)
def update_class_points_from_column_score(sender, instance, **kwargs):
    """独自評価項目の得点更新時に成績を再計算"""
    if instance.column.classroom:
        try:
            scp = StudentClassPoints.objects.get(
                student=instance.student,
                classroom=instance.column.classroom
            )
            scp.recalculate_total()
        except StudentClassPoints.DoesNotExist:
            if kwargs.get('signal') == post_save:
                scp = StudentClassPoints.objects.create(
                    student=instance.student,
                    classroom=instance.column.classroom
                )
                scp.recalculate_total()
