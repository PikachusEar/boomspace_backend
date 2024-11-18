from django.urls import path
from .views import home, wechat_login, available_timeslots, make_reservation, view_reservations_and_balance, view_user_info, update_user_info, get_images, make_combo_reservation
from django.contrib import admin

# 修改admin站点的标题
admin.site.site_header = 'Boomsapce Administration'    # 设置网站页头
admin.site.site_title = 'Boomspace Admin'         # 设置网站标题
admin.site.index_title = 'Boomspace Admin'        # 设置首页标题

urlpatterns = [
    path('', home, name='home'),
    path('wechat_login', wechat_login, name='wechat_login'),
    path('available_timeslots', available_timeslots, name='available_timeslots'),
    path('make_reservation', make_reservation, name='make_reservation'),
    #path('test_login/', test_login, name='test_login'),
    path('view_reservations_and_balance/', view_reservations_and_balance, name='view_reservations_and_balance'),
    path('view_user_info/', view_user_info, name='view_user_info'),
    path('update_user_info/', update_user_info, name='update_user_info'),
    path('get_images/', get_images, name='get_images(homepage)'),
    path('make_combo_reservation', make_combo_reservation, name='make_combo_reservation'),

]


