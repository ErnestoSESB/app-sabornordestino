from .views import garcom_user


def usuario_painel(request):
    return {
        'usuario_e_garcom': garcom_user(request.user),
    }
