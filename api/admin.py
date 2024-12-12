from django.contrib import messages
from django.db import transaction
from .models import User, Court, TimeSlot, Reservation, News, Image, CourtCombo, RechargeRecord, f_Image, f_News, isActivated
from datetime import timedelta
import csv
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
from django.utils.timezone import now
import calendar
from datetime import datetime
import json
from django.core.serializers.json import DjangoJSONEncoder

class ExportCsvMixin:
    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        response = HttpResponse(content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="{meta.verbose_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow(field_names)
        for obj in queryset:
            row = []
            for field in field_names:
                value = getattr(obj, field)
                row.append(str(value))
            writer.writerow(row)

        return response

    export_as_csv.short_description = "Export selected items to CSV"



class UserAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ['user_id','wechat_nickname', 'phone', 'email', 'first_name', 'last_name', 'gender', 'birth_date', 'wallet_balance', 'date_joined']
    search_fields = ['user_id','wechat_nickname', 'first_name', 'last_name', 'wechat_id', 'phone', 'email']
    actions = ['export_as_csv']


class ReservationAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ('user', 'date', 'timeslot', 'status', 'unique_id', 'created_at')
    search_fields = ('unique_id', 'user__wechat_nickname', 'user__email', 'user__phone')
    readonly_fields = ('unique_id',)
    ordering = ('-created_at',)
    actions = ['export_as_csv']
    change_list_template = 'admin/reservation/reservation_changelist.html'
    autocomplete_fields = ['user', 'timeslot']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('calendar/', self.admin_site.admin_view(self.calendar_view), name='reservation-calendar'),
        ]
        return custom_urls + urls

    def calendar_view(self, request):
        year = request.GET.get('year')
        month = request.GET.get('month')
        selected_court = request.GET.get('court', 'all')

        today = now().date()
        year = int(year) if year else today.year
        month = int(month) if month else today.month

        start_date = datetime(year, month, 1).date()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).date()
        else:
            end_date = datetime(year, month + 1, 1).date()

        # 获取所有活跃的场地
        courts = Court.objects.filter(is_active=True)

        # 基础查询集
        reservations = Reservation.objects.filter(
            date__gte=start_date,
            date__lt=end_date
        ).select_related('user', 'timeslot', 'timeslot__court')

        # 如果选择了特定场地，则过滤预约
        if selected_court != 'all':
            reservations = reservations.filter(timeslot__court_id=selected_court)

        # 按日期和场地组织预约数据
        reservation_dates = {}
        for res in reservations:
            date_key = res.date
            court_id = str(res.timeslot.court.id)

            if date_key not in reservation_dates:
                reservation_dates[date_key] = {}

            if court_id not in reservation_dates[date_key]:
                reservation_dates[date_key][court_id] = {
                    'count': 0,
                    'reservations': []
                }

            reservation_dates[date_key][court_id]['count'] += 1
            reservation_dates[date_key][court_id]['reservations'].append({
                'id': res.id,
                'user': {
                    'wechat_nickname': res.user.wechat_nickname,
                },
                'timeslot': {
                    'start_time': res.timeslot.start_time.strftime("%H:%M"),
                    'end_time': res.timeslot.end_time.strftime("%H:%M"),
                    'court': {
                        'name': res.timeslot.court.name,
                        'id': res.timeslot.court.id
                    }
                },
                'status': res.status
            })

        cal = calendar.monthcalendar(year, month)
        calendar_data = []

        for week in cal:
            week_data = []
            for day in week:
                if day == 0:
                    week_data.append({
                        'day': None,
                        'reservations': {},
                        'reservation_count': 0,
                        'is_today': False
                    })
                else:
                    current_date = datetime(year, month, day).date()
                    date_data = reservation_dates.get(current_date, {})

                    if selected_court != 'all':
                        court_data = date_data.get(selected_court, {'count': 0, 'reservations': []})
                        court_reservations = {selected_court: court_data}
                    else:
                        court_reservations = date_data

                    total_count = sum(
                        data['count'] for data in court_reservations.values()) if court_reservations else 0

                    week_data.append({
                        'day': day,
                        'reservations': json.dumps(court_reservations, cls=DjangoJSONEncoder),
                        'reservation_count': total_count,
                        'is_today': current_date == today,
                        'date': current_date
                    })
            calendar_data.append(week_data)

        context = {
            'title': f'{year}年{month}月预订日历',
            'year': year,
            'month': month,
            'calendar_data': calendar_data,
            'month_name': calendar.month_name[month],
            'prev_month': {'year': year if month > 1 else year - 1, 'month': month - 1 if month > 1 else 12},
            'next_month': {'year': year if month < 12 else year + 1, 'month': month + 1 if month < 12 else 1},
            'today': today,
            'opts': self.model._meta,
            'courts': courts,
            'selected_court': selected_court,
        }

        return TemplateResponse(request, "admin/reservation/calendar.html", context)

class NewsAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ('title', 'url', 'image', 'description')
    search_fields = ('title',)
    actions = ['export_as_csv']

class ImageAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ('title', 'image', 'description')
    search_fields = ('title',)
    actions = ['export_as_csv']

class CourtAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ['name', 'description', 'timerange', 'is_active']
    search_fields = ['name']
    actions = ['export_as_csv']

class CourtComboAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ['name','description','is_active']
    search_fields = ['name']
    actions = ['export_as_csv']


class TimeSlotAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ['court', 'start_time', 'end_time', 'day_of_week', 'price', 'is_peak', 'is_active']
    list_filter = ['court', 'day_of_week', 'is_peak']
    search_fields = ['court__name']
    actions = ['export_as_csv']
    change_list_template = 'admin/timeslot/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('batch-create/', self.admin_site.admin_view(self.batch_create_view), name='batch-create-timeslots'),
        ]
        return custom_urls + urls

    def batch_create_view(self, request):
        if request.method == 'POST':
            try:
                # 获取表单数据
                court_id = request.POST.get('court')
                start_time_str = request.POST.get('start_time')
                end_time_str = request.POST.get('end_time')
                duration = int(request.POST.get('duration'))
                price = float(request.POST.get('price'))
                day_of_week = int(request.POST.get('day_of_week'))
                is_peak = request.POST.get('is_peak') == 'on'

                # 转换时间字符串为time对象（24小时制）
                try:
                    start_time = datetime.strptime(start_time_str, '%H:%M').time()
                    end_time = datetime.strptime(end_time_str, '%H:%M').time()
                except ValueError as e:
                    raise ValueError(f"Invalid time format. Please use 24-hour format (HH:MM). Error: {str(e)}")

                # 获取Court实例
                court = Court.objects.get(id=court_id)

                # 使用当前日期作为基准计算时间差
                base_date = datetime.now().date()
                start_dt = datetime.combine(base_date, start_time)
                end_dt = datetime.combine(base_date, end_time)

                # 处理跨越午夜的情况
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)

                # 创建时间段
                current_dt = start_dt
                created_count = 0

                with transaction.atomic():
                    while current_dt + timedelta(minutes=duration) <= end_dt:
                        next_dt = current_dt + timedelta(minutes=duration)

                        TimeSlot.objects.create(
                            court=court,
                            start_time=current_dt.time(),
                            end_time=next_dt.time(),
                            day_of_week=day_of_week,
                            price=price,
                            is_peak=is_peak
                        )
                        created_count += 1
                        current_dt = next_dt

                messages.success(request, f'Successfully created {created_count} time slots')
                return HttpResponseRedirect("../")

            except Exception as e:
                messages.error(request, f'Error creating time slots: {str(e)}')
                return HttpResponseRedirect("../")

        # GET请求显示表单
        context = {
            'title': 'Batch Create Time Slots',
            'courts': Court.objects.all(),
            'day_choices': [
                (0, 'Every day'),
                (1, 'Monday'),
                (2, 'Tuesday'),
                (3, 'Wednesday'),
                (4, 'Thursday'),
                (5, 'Friday'),
                (6, 'Saturday'),
                (7, 'Sunday'),
            ]
        }

        return TemplateResponse(request, "admin/timeslot_batch_create.html", context)


class RechargeRecordAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ['user', 'amount', 'created_at', 'admin_user', 'notes']
    search_fields = ['user__wechat_nickname', 'user__wechat_id', 'notes']
    readonly_fields = ['created_at', 'admin_user']
    actions = ['export_as_csv']
    list_filter = ['created_at']

    # 添加自动完成字段
    autocomplete_fields = ['user']

    def save_model(self, request, obj, form, change):
        if not change:  # 只在创建新记录时执行
            try:
                with transaction.atomic():
                    # 设置管理员用户
                    obj.admin_user = request.user

                    # 更新用户余额
                    user = obj.user
                    user.wallet_balance += obj.amount
                    user.save()

                    # 保存充值记录
                    super().save_model(request, obj, form, change)

                    messages.success(request,
                                     f'成功为用户 {user.wechat_nickname} 充值 ${obj.amount}，当前余额: ${user.wallet_balance}')
            except Exception as e:
                messages.error(request, f'充值失败: {str(e)}')
        else:
            messages.error(request, '充值记录不允许修改')

    def has_change_permission(self, request, obj=None):
        return False  # 禁止修改充值记录


class f_ImageAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ('title', 'image', 'description')
    search_fields = ('title',)


class f_NewsAdmin(admin.ModelAdmin):
    list_display = ('title', 'url', 'image', 'description')
    search_fields = ('title',)




admin.site.register(User, UserAdmin)
admin.site.register(Court, CourtAdmin)
admin.site.register(TimeSlot, TimeSlotAdmin)
admin.site.register(Reservation, ReservationAdmin)
admin.site.register(News, NewsAdmin)
admin.site.register(Image, ImageAdmin)
admin.site.register(CourtCombo, CourtComboAdmin)
admin.site.register(RechargeRecord, RechargeRecordAdmin)
admin.site.register(f_News, NewsAdmin)
admin.site.register(f_Image, ImageAdmin)
admin.site.register(isActivated)
