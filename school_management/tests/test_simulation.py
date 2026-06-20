from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import LessonSession, ClassRoom
from school_management.views.peer_eval.results import save_peer_evaluation_simulation

User = get_user_model()

class SimulationLogicTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(
            email='teacher@example.com',
            password='password123',
            role='teacher',
            first_name='Teacher',
            last_name='Test',
            full_name='Teacher Test'
        )
        self.classroom = ClassRoom.objects.create(
            class_name='Test Class',
            year=2024,
            semester='first'
        )
        self.classroom.teachers.add(self.teacher)
        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            topic='Test Session',
            has_peer_evaluation=True
        )

    def test_save_simulation_data(self):
        self.client.force_login(self.teacher)
        url = reverse('school_management:save_peer_evaluation_simulation', args=[self.session.id])
        
        post_data = {
            'sim_member_rank_1_10': '2',
            'sim_member_rank_2_10': '1',
            'sim_contrib_10': '4.5',
            'sim_group_rank_1_10': '3',
            'sim_group_score_20': '10', # Old fallback
        }
        
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302) # Redirects
        
        session = self.client.session
        sim_data = session.get('peer_sim_points', {})
        class_id_str = str(self.classroom.id)
        sess_id_str = str(self.session.id)
        
        self.assertIn(class_id_str, sim_data)
        self.assertIn(sess_id_str, sim_data[class_id_str])
        
        student_data = sim_data[class_id_str][sess_id_str]
        
        # Test new rank structure
        self.assertIn('10', student_data)
        self.assertEqual(student_data['10']['member_rank_1'], 2.0)
        self.assertEqual(student_data['10']['member_rank_2'], 1.0)
        self.assertEqual(student_data['10']['contrib'], 4.5)
        self.assertEqual(student_data['10']['group_rank_1'], 3.0)
        
        # Test old fallback structure
        self.assertIn('20', student_data)
        self.assertEqual(student_data['20']['group'], 10.0)

    def test_class_points_simulation_calculation(self):
        # Create student and settings for calculation
        self.student = User.objects.create_user(
            email='student@example.com',
            password='password123',
            role='student',
            first_name='Student',
            last_name='Test',
            full_name='Student Test'
        )
        self.classroom.students.add(self.student)
        
        from school_management.models import PeerEvaluationSettings
        PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_member_evaluation=True,
            member_scores=[5, 3],
            enable_group_evaluation=True,
            group_scores=[4, 2]
        )

        # Inject session data
        session = self.client.session
        session['test_mode'] = True
        session['peer_sim_points'] = {
            str(self.classroom.id): {
                str(self.session.id): {
                    str(self.student.id): {
                        'member_rank_1': 2, # 2 votes * 5 points = 10
                        'member_rank_2': 1, # 1 vote * 3 points = 3
                        'contrib': 4.5,     # + 4.5 points = 17.5
                        'group_rank_1': 1,  # 1 vote * 4 points = 4
                        'group_rank_2': 0   # 0 votes = 0 -> 4
                    }
                }
            }
        }
        session.save()

        self.client.force_login(self.teacher)
        url = reverse('school_management:class_points', args=[self.classroom.id])
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Check context for calculated peer total
        student_grades = response.context.get('student_grades', [])
        found = False
        for row in student_grades:
            if row['student'].id == self.student.id:
                # In settings mode, contrib is not added.
                # member_rank_1 (2*5) + member_rank_2 (1*3) + group_rank_1 (1*4) = 17.0
                self.assertEqual(row['peer_total'], 17.0)
                found = True
        self.assertTrue(found)

    def test_class_evaluation_simulation_calculation(self):
        # Create student and settings for calculation
        self.student = User.objects.create_user(
            email='student2@example.com',
            password='password123',
            role='student',
            first_name='Student2',
            last_name='Test',
            full_name='Student2 Test'
        )
        self.classroom.students.add(self.student)
        
        from school_management.models import PeerEvaluationSettings
        PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_member_evaluation=True,
            member_scores=[10, 5],
            enable_group_evaluation=True,
            group_scores=[8, 4]
        )

        # Inject session data
        session = self.client.session
        session['test_mode'] = True
        session['peer_sim_points'] = {
            str(self.classroom.id): {
                str(self.session.id): {
                    str(self.student.id): {
                        'member_rank_1': 1, # 1 vote * 10 points = 10
                        'group_rank_2': 2   # 2 votes * 4 points = 8
                    }
                }
            }
        }
        session.save()

        self.client.force_login(self.teacher)
        url = reverse('school_management:class_evaluation', args=[self.classroom.id])
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Check context for calculated total_score (in class_evaluation_view)
        student_evaluations = response.context.get('student_evaluations', [])
        found = False
        for s_data in student_evaluations:
            if s_data['student'].id == self.student.id:
                # In class_evaluation_view, peer points are usually mapped by session or aggregated
                # In class_evaluation_view, peer points are usually aggregated in total_peer_score
                # simulated_peer_points for this session should be 1*10 + 2*4 = 18
                self.assertEqual(s_data['total_peer_score'], 18.0)
                found = True
        self.assertTrue(found)
