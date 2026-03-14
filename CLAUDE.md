# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Django 5.2.5 web application for educational institutions (学校管理システム). Teacher-facing system for class/student/quiz/peer-evaluation management. Uses `uv` for package management. SQLite3 in development, PostgreSQL in production (Railway). Deployed via GitHub push to Railway (auto-deploy).

## Development Commands

```bash
uv sync                                  # Install dependencies
uv run python manage.py migrate          # Apply database migrations
uv run python manage.py makemigrations   # Create migration files
uv run python manage.py runserver        # Start at http://127.0.0.1:8000/
uv run python manage.py createsuperuser  # Create admin user (email as username)
uv run python manage.py shell            # Django Python shell
uv run python manage.py dbshell          # Access database shell
```

No test suite exists. Manual testing via `uv run python test_login.py` and `uv run python create_test_users.py`.

## Architecture

### Project Structure
- **`school_project/`**: Django settings and root URL configuration
- **`school_management/`**: Single-app architecture with all business logic
  - `models.py`: All data models (~1050 lines) including signal handlers at the bottom
  - `views/`: Split by feature domain (10 subdirectories), each with `__init__.py` re-exporting view functions
  - `urls.py`: URL routing (`app_name='school_management'`)
  - `templates/school_management/`: All HTML templates

### View Directory Mapping
| Directory | Purpose | Key files |
|-----------|---------|-----------|
| `auth/` | Login/logout | `login.py`, `logout.py` |
| `dashboard/` | Dashboards | `dashboard_view.py`, `teacher_dashboard.py`, `student_dashboard.py` |
| `classes/` | Class CRUD | `list.py`, `detail.py`, `management.py` |
| `sessions/` | Lesson sessions | `management.py`, `detail.py`, `list.py`, `lesson.py` |
| `students/` | Student CRUD | `list.py`, `detail.py`, `management.py`, `enrollment.py`, `self_eval.py` |
| `quizzes/` | Quiz & grading | `management.py`, `grading.py`, `questions.py` |
| `groups/` | Group management | `read.py`, `write.py`, `master.py` |
| `peer_eval/` | Peer evaluation | `management.py`, `form.py`, `improved.py`, `results.py` |
| `grades/` | Evaluation & points | `class_evaluation.py`, `class_points.py` |
| `attendance/` | QR code & scans | `manage.py`, `scan.py`, `student.py`, `utils.py` |

### User Model
**Critical**: Uses `CustomUser` (extends `AbstractUser`) as the unified user model:
- `AUTH_USER_MODEL = 'school_management.CustomUser'`
- Email-based authentication (`USERNAME_FIELD = 'email'`)
- Role field: `'admin'`, `'teacher'`, `'student'`
- `Teacher` and `Student` are aliases for `CustomUser` (backward compatibility)
- Properties: `is_teacher` (admin/teacher roles), `is_student` (student role)
- Students do NOT log in to this system; only teachers/admins use the login

### Points & Grading System
Two grading modes per class (`ClassRoom.grading_system`):
- **`standard`**: Points accumulated from quizzes + lesson points + QR scans + peer evaluation. Formula: `attendance_points + (class_points * 2)`
- **`goal`**: Teacher directly assigns a score via `SelfEvaluation.teacher_score`

Points hierarchy:
- `StudentClassPoints`: Aggregated per-student per-class total. Auto-recalculated on `save()` via `calculate_points_internal()`
- `StudentLessonPoints`: Per-student per-session manual points
- `QuizScore`: Per-quiz results
- `QRCodeScan`: Scan history, converted to `QuizScore` via signals

Signal handlers in `models.py` (line ~889+) auto-recalculate `StudentClassPoints` when `QuizScore`, `StudentLessonPoints`, `SelfEvaluation`, `QRCodeScan`, `ContributionEvaluation`, `PeerEvaluation`, or `GroupMember` changes.

### Peer Evaluation Dual-Lookup Pattern
`PeerEvaluation` stores group references as both FK (`first_place_group`) and number (`first_place_group_number`). The `save()` method syncs numbers from FKs. Queries use OR conditions to handle both:
```python
Q(first_place_group=g) | Q(lesson_session=sess, first_place_group_number=g.group_number)
```

### QR Code Flow
1. Teacher scans student's `StudentQRCode` (UUID-based)
2. `QRCodeScan` created → `pre_save` signal sets `points_awarded` from `classroom.qr_point_value`
3. `post_save` signal creates/updates a `QuizScore` on the `is_qr_linked` Quiz for that session
4. `QuizScore` save triggers `StudentClassPoints` recalculation

### Key URL Patterns
- `/`: Login → `/dashboard/`: Teacher dashboard
- `/classes/<id>/evaluation/`: Grade evaluation view
- `/classes/<id>/points/`: Points ranking view
- `/peer-evaluation/<token>/`: Anonymous student evaluation (UUID token)
- `/qr/<uuid>/`: QR code scan endpoint

### Known Architecture Notes
- `sessions/__init__.py` has aliasing that makes `lesson.py`'s `lesson_session_create` and `lesson_session_detail` dead code (overridden by `management.py` and `detail.py`)
- `class_points.py` has N+1 optimization with pre-cached session rankings; `class_evaluation.py` still has the N+1 pattern for peer evaluation queries
- `class_evaluation.py` has significant dead code: many computed keys in `student_evaluations` dict (`total_combined_score`, `multiplied_points`, `multiplier`, `session_data`, `session_count`, `average_points`, `class_points`, `student_points`, `qr_points`) and context variables (`session_list`, `session_peer_averages`) are never used in the template
- `models.py` `calculate_points_internal()` previously had a `scanned_by=self.student` filter bug for QR points — now resolved by aggregating QR points via `QuizScore` instead of `QRCodeScan` directly
