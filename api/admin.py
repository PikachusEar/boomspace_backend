from django.contrib import admin
from .models import User, Court, TimeSlot, Reservation, News, Image, CourtCombo
from django.http import HttpResponse
import csv
from datetime import datetime

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
    list_display = ['wechat_id', 'wechat_nickname', 'phone', 'email', 'first_name', 'last_name', 'gender', 'birth_date', 'wallet_balance', 'date_joined']
    search_fields = ['wechat_nickname', 'first_name', 'last_name', 'wechat_id', 'phone', 'email']
    actions = ['export_as_csv']

class ReservationAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ('user', 'date', 'timeslot', 'status', 'unique_id', 'created_at')
    search_fields = ('unique_id', 'user__wechat_nickname', 'status')
    readonly_fields = ('unique_id',)  # 确保 UUID 字段是只读的
    ordering = ('-created_at',)
    actions = ['export_as_csv']

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

admin.site.register(User, UserAdmin)
admin.site.register(Court, CourtAdmin)
admin.site.register(TimeSlot, TimeSlotAdmin)
admin.site.register(Reservation, ReservationAdmin)
admin.site.register(News, NewsAdmin)
admin.site.register(Image, ImageAdmin)
admin.site.register(CourtCombo, CourtComboAdmin)