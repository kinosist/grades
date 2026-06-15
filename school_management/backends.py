from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

UserModel = get_user_model()

class EmailAuthBackend(ModelBackend):
    """
    メールアドレスが重複していても、パスワードが一致するユーザーを特定してログインさせる
    カスタム認証バックエンド。
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            # 同じメールアドレスを持つユーザーを全て取得
            users = UserModel._default_manager.filter(**{UserModel.USERNAME_FIELD: username})
            for u in users:
                if u.check_password(password) and self.user_can_authenticate(u):
                    return u
            return None
        
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
            
        return None
