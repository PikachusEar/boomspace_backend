from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
import uuid

class UserManager(BaseUserManager):
    def create_user(self, wechat_id, email, password='123456', **extra_fields):
        if not wechat_id:
            raise ValueError('WeChat ID must be set')
        email = self.normalize_email(email)
        user = self.model(wechat_id=wechat_id, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, wechat_id, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(wechat_id, email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    wechat_id = models.CharField(max_length=255, unique=True, help_text="微信唯一标识符")
    wechat_nickname = models.CharField(max_length=100, blank=True, null=True, help_text="微信昵称")
    email = models.EmailField(blank=True, null=True, help_text="电子邮箱")
    phone = models.CharField(max_length=20, blank=True, help_text="联系电话")
    last_name = models.CharField(max_length=30, blank=True, help_text="姓")
    first_name = models.CharField(max_length=30, blank=True, help_text="名")
    gender = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')], blank=True, help_text="性别")
    birth_date = models.DateField(null=True, blank=True, help_text="出生年月")
    wallet_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="钱包余额")
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'wechat_id'
    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return f"{self.wechat_nickname} ({self.wechat_id})"



class Court(models.Model):
    name = models.CharField(max_length=100, help_text="场地名称")
    description = models.TextField(blank=True, help_text="场地描述")
    timerange = models.IntegerField(default=14, help_text="场地可预约的时间范围，默认为14天(两周)，如需更改可以自行增加或者减少")
    is_active = models.BooleanField(default=True, help_text="是否激活该场地")

    def __str__(self):
        return self.name


class CourtCombo(models.Model):
    name = models.CharField(max_length=100,default='combo', help_text="场地组合名称")
    combined_courts = models.ManyToManyField(Court, help_text="两个或更多组合的场地")
    discount = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="折扣值（可选）")
    description = models.TextField(blank=True, help_text="组合描述")
    fixed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="固定价格（可选）")
    is_active = models.BooleanField(default=True, help_text="是否激活该组合")

    def __str__(self):
        return f"Combo: {', '.join([court.name for court in self.combined_courts.all()])}"


class TimeSlot(models.Model):
    court = models.ForeignKey(Court, on_delete=models.CASCADE, related_name="timeslots", help_text="关联的场地")
    start_time = models.TimeField(help_text="开始时间")
    end_time = models.TimeField(help_text="结束时间")
    day_of_week = models.IntegerField(default=0, help_text="周几：1=周一，2=周二, ... ,7=周日, 0=每天")
    price = models.DecimalField(max_digits=6, decimal_places=2, help_text="价格")
    is_peak = models.BooleanField(default=False, help_text="是否为高峰时段")
    is_active = models.BooleanField(default=True, help_text="是否激活")

    def __str__(self):
        return f"{self.court.name} from {self.start_time} to {self.end_time} - {'Peak' if self.is_peak else 'Off-peak'}"


class Reservation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reservations", help_text="预约的用户")
    date = models.DateField(null=True, help_text="预约日期")
    timeslot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name="reservations",
                                 help_text="预约的时间段")
    price = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text="预定价格")
    is_combo = models.BooleanField(default=False, help_text="是否为组合价格")
    status = models.CharField(max_length=50,
                              choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')],
                              default='pending', help_text="预约状态")
    created_at = models.DateTimeField(auto_now_add=True, help_text="预约创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="预约最后更新时间")
    unique_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, help_text="订单唯一标识符")

    def __str__(self):
        return f"{self.user} - {self.timeslot} - {self.status}"

class Image(models.Model):
    image = models.ImageField(upload_to='images/')
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.title


class News(models.Model):
    image = models.ImageField(upload_to='news_images/', help_text="上传一张新闻图片")
    title = models.CharField(max_length=255, help_text="新闻标题")
    description = models.TextField(help_text="新闻描述")
    url = models.URLField(max_length=200, help_text="新闻详情的链接")

    def __str__(self):
        return self.title

class RechargeRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recharge_records', help_text="充值用户")
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="充值金额")
    created_at = models.DateTimeField(auto_now_add=True, help_text="充值时间")
    notes = models.CharField(max_length=255, blank=True, help_text="备注")
    admin_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_recharges', help_text="操作管理员")

    def __str__(self):
        return f"{self.user.wechat_nickname} - ${self.amount} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        verbose_name = "Charge Record"
        verbose_name_plural = "Charge Record"
        ordering = ['-created_at']