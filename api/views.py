import uuid
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from datetime import datetime, timedelta
from .models import User, TimeSlot, Reservation, Court, Image, News, CourtCombo
import requests
from django.db.models import Q
from collections import defaultdict
from decimal import Decimal
import json
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.utils.timezone import localtime
from django.conf import settings

def home(request):
    return HttpResponse("Hello, world. This is the API home page.")


@api_view(['GET'])
def wechat_login(request):
    js_code = request.GET.get('code')
    if not js_code:
        return JsonResponse({"message": "Invalid request. This URL only handles login requests"}, status=400)

    appid = 'wxf6763bd29ed9f729'
    secret = '27c0745e1765f6f910aea2ede37f6009'
    url = f"https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={js_code}&grant_type=authorization_code"

    response = requests.get(url)
    data = response.json()

    if 'errcode' in data and data['errcode'] != 0:
        return JsonResponse({'status': 'error', 'message': f"微信登录失败: {data.get('errmsg', 'Unknown error')}"},
                            status=403)

    wechat_id = data.get('openid')
    wechat_nickname = 'WeChat User'

    # 查找或创建用户
    user, created = User.objects.get_or_create(wechat_id=wechat_id, defaults={
        'wechat_nickname': wechat_nickname,
        # 可以设置其他默认值
    })

    # 为用户创建或获取现有的Token
    token, created = Token.objects.get_or_create(user=user)

    # 返回Token而不是进行重定向
    return JsonResponse({
        'status': 'success',
        'message': '登录成功',
        'token': token.key,
        'is_new_user': created
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def available_timeslots(request):
    now = timezone.now()
    all_courts = Court.objects.filter(is_active=True)
    all_combos = CourtCombo.objects.filter(is_active=True).prefetch_related('combined_courts')
    timeslots_data = []

    # Process individual courts and their timeslots
    for court in all_courts:
        timerange = court.timerange
        future_dates = [now + timedelta(days=i) for i in range(timerange)]
        valid_dates = [date.date() for date in future_dates]

        future_timeslots = TimeSlot.objects.filter(court=court, is_active=True)
        reservations = Reservation.objects.filter(
            timeslot__in=future_timeslots,
            date__in=valid_dates,
            status__in=['confirmed', 'pending']
        )

        reserved_timeslot_dates = defaultdict(set)
        for reservation in reservations:
            reserved_timeslot_dates[reservation.timeslot_id].add(reservation.date)

        for timeslot in future_timeslots:
            for date in valid_dates:
                if (date.isoweekday() == timeslot.day_of_week or timeslot.day_of_week == 0) and date not in reserved_timeslot_dates[timeslot.id]:
                    timeslots_data.append({
                        'timeslot_id': timeslot.id,
                        'court_id': court.id,
                        'court_name': court.name,
                        'start_time': timeslot.start_time.strftime("%H:%M"),
                        'end_time': timeslot.end_time.strftime("%H:%M"),
                        'price': float(timeslot.price),
                        'is_peak': timeslot.is_peak,
                        'date': date.strftime("%Y-%m-%d"),
                        'is_combo': False,
                        'combo_courts': None
                    })

    # Process combos
    combo_timeslots = []
    for combo in all_combos:
        combo_courts = combo.combined_courts.all()
        if not all(court.is_active for court in combo_courts):
            continue  # Skip if any court in the combo is inactive

        # Group available timeslots by date and time
        timeslot_groups = defaultdict(list)
        for timeslot in timeslots_data:
            key = (timeslot['date'], timeslot['start_time'], timeslot['end_time'])
            timeslot_groups[key].append(timeslot)

        # Check for combo availability
        for (date, start_time, end_time), group in timeslot_groups.items():
            if len(group) == len(combo_courts) and all(ts['court_id'] in [court.id for court in combo_courts] for ts in group):
                total_price = sum(ts['price'] for ts in group)
                if combo.fixed_price:
                    price = combo.fixed_price
                elif combo.discount:
                    discount = float(combo.discount)
                    price = round(total_price * discount, 2)
                else:
                    price = total_price

                combo_timeslots.append({
                    'timeslot_ids': [tss['timeslot_id'] for tss in group],
                    'court_name': combo.name,
                    'combo_id': combo.id,
                    'start_time': start_time,
                    'end_time': end_time,
                    'price': float(price),
                    'is_peak': any(ts['is_peak'] for ts in group),
                    'date': date,
                    'is_combo': True,
                    'combo_courts': [court.name for court in combo_courts]
                })

    # Combine individual and combo timeslots
    timeslots_data.extend(combo_timeslots)

    return JsonResponse({'available_timeslots': timeslots_data})



@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def make_reservation(request):
    # 从请求中获取时间段ID和预定日期
    timeslot_id = request.data.get('timeslot_id')
    reservation_date = request.data.get('date')

    try:
        # 尝试获取对应的时间段对象
        timeslot = TimeSlot.objects.get(id=timeslot_id, court__timerange__gte=(timezone.now().date() - timezone.datetime.strptime(reservation_date, "%Y-%m-%d").date()).days)
    except TimeSlot.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': '所选时间段不存在'}, status=404)

    # 检查是否已有预定占用该时间段
    if Reservation.objects.filter(Q(timeslot=timeslot, date=reservation_date), Q(status='pending') | Q(status='confirmed')).exists():
        return JsonResponse({'status': 'error', 'message': '预定失败：位置已被预订'}, status=400)

    user = request.user  # 从token中获取用户信息

    # 检查用户钱包余额是否足够支付场地费用
    if user.wallet_balance < timeslot.price:
        return JsonResponse({'status': 'error', 'message': '预定失败，账户余额不足'}, status=400)

    # 扣除用户余额并保存
    user.wallet_balance -= timeslot.price
    user.save()

    # 创建预订
    reservation = Reservation.objects.create(
        user=user,
        timeslot=timeslot,
        date=reservation_date,
        price=timeslot.price,
        status='pending'  # 默认为待确认状态
    )

    # 返回成功信息及预订详情
    return JsonResponse({
        'status': 'success',
        'message': '预订成功，请在我的预定中查看预定详情',
        'reservation_id': str(reservation.unique_id)  # 返回预订的唯一标识符
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def make_combo_reservation(request):
    # 从请求中获取时间段ID列表、预定日期和组合场地ID
    timeslot_ids = request.data.get('timeslot_ids', [])
    reservation_date = request.data.get('date')
    combo_id = request.data.get('combo_id')

    if not timeslot_ids or not reservation_date or not combo_id:
        return JsonResponse({'status': 'error', 'message': 'Missing required data'}, status=400)

    try:
        # 解析预定日期
        reservation_date = datetime.strptime(reservation_date, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid date format'}, status=400)

    try:
        # 获取组合场地信息
        combo = CourtCombo.objects.get(id=combo_id, is_active=True)
        combo_courts = combo.combined_courts.filter(is_active=True)

        # 获取时间段信息
        timeslots = TimeSlot.objects.filter(
            id__in=timeslot_ids,
            is_active=True,
            court__in=combo_courts,
            court__timerange__gte=(timezone.now().date() - reservation_date).days
        )

        if len(timeslots) != len(timeslot_ids) or len(timeslots) != len(combo_courts):
            return JsonResponse({'status': 'error', 'message': '所选时间段不存在、不可用或数量不匹配'}, status=404)

    except (CourtCombo.DoesNotExist, TimeSlot.DoesNotExist):
        return JsonResponse({'status': 'error', 'message': '所选组合场地或时间段不存在'}, status=404)

    # 检查是否已有预定占用该时间段
    if Reservation.objects.filter(Q(timeslot__in=timeslots, date=reservation_date), Q(status='pending') | Q(status='confirmed')).exists():
        return JsonResponse({'status': 'error', 'message': '预定失败：一个或多个时间段已被预订'}, status=400)

    user = request.user  # 从token中获取用户信息

    # 计算总价格
    total_price = sum(timeslot.price for timeslot in timeslots)
    if combo.fixed_price:
        price = combo.fixed_price
    elif combo.discount:
        price = round(total_price * Decimal(str(combo.discount)), 2)
    else:
        price = total_price

    # 检查用户钱包余额是否足够支付场地费用
    if user.wallet_balance < price:
        return JsonResponse({'status': 'error', 'message': '预定失败，账户余额不足'}, status=400)

    # 扣除用户余额并保存
    user.wallet_balance -= price
    user.save()

    # 创建预订
    reservations = []
    individual_price = (price / len(timeslots)).quantize(Decimal('0.01'))
    for timeslot in timeslots:
        reservation = Reservation.objects.create(
            user=user,
            timeslot=timeslot,
            date=reservation_date,
            price=individual_price,
            status='pending',  # 保持与make_reservation一致，使用'pending'状态
            is_combo=True

        )
        reservations.append(reservation)

    # 返回成功信息及预订详情
    return JsonResponse({
        'status': 'success',
        'message': '预订成功，请在我的预定中查看预定详情',
        'reservation_ids': [str(res.unique_id) for res in reservations],  # 返回所有预订的唯一标识符
        'total_price': str(price),
        'individual_price': str(individual_price)
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def view_reservations_and_balance(request):
    user = request.user  # 用户通过Token进行验证并通过Django的session获取

    # 获取用户的所有预定信息
    reservations = Reservation.objects.filter(user=user).values(
        'date', 'created_at', 'timeslot__start_time', 'timeslot__end_time', 'timeslot__court__name', 'status'
    ).order_by('date', 'timeslot__start_time')

    # 准备预定信息
    reservations_data = [{
        'date': reservation['date'].strftime("%Y-%m-%d"),
        'created_at': localtime(reservation['created_at']).strftime("%Y-%m-%d %H:%M"),
        'start_time': reservation['timeslot__start_time'].strftime("%H:%M"),
        'end_time': reservation['timeslot__end_time'].strftime("%H:%M"),
        'court_name': reservation['timeslot__court__name'],
        'status': reservation['status']
    } for reservation in reservations]

    # 获取用户的钱包余额
    wallet_balance = user.wallet_balance

    # 返回预定信息和钱包余额
    return Response({
        'reservations': reservations_data,
        'wallet_balance': float(wallet_balance)
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def view_user_info(request):
    user = request.user
    user_data = {
        'wechat_nickname': user.wechat_nickname,
        'email': user.email,
        'phone': user.phone,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'gender': user.gender,
        'birth_date': user.birth_date.strftime('%Y-%m-%d') if user.birth_date else None,
        'wallet_balance': user.wallet_balance
    }
    return JsonResponse(user_data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def update_user_info(request):
    user = request.user
    data = request.data
    user.wechat_nickname = data.get('wechat_nickname', user.wechat_nickname)
    user.email = data.get('email', user.email)
    user.phone = data.get('phone', user.phone)
    user.first_name = data.get('first_name', user.first_name)
    user.last_name = data.get('last_name', user.last_name)
    user.gender = data.get('gender', user.gender)
    user.birth_date = data.get('birth_date', user.birth_date)

    user.save()
    return JsonResponse({'message': 'User information updated successfully'})

@api_view(['GET'])
def get_images(request):
    images = Image.objects.all()
    newses = News.objects.all()

    image_data = [
        {
            'image_url': request.build_absolute_uri(settings.MEDIA_URL + image.image.name),  # 需要配置
            'title': image.title,
            'description': image.description,
        } for image in images
    ]

    news_data = [
        {
            'url': news.url,
            'title': news.title,
            'description': news.description,
            'image_url': request.build_absolute_uri(settings.MEDIA_URL + news.image.name)  # 需要配置

        } for news in newses
    ]
    return JsonResponse({'images': image_data, 'news': news_data})


#@api_view(['GET'])
#def test_login(request):
#    wechat_id = request.GET.get('wechat_id')
#    if not wechat_id:
#        return JsonResponse({'status': 'error', 'message': 'No wechat_id provided'}, status=400)
#    User = get_user_model()
#    try:
#        user = User.objects.get(wechat_id=wechat_id)
#    except User.DoesNotExist:
#        return JsonResponse({'status': 'error', 'message': 'User does not exist'}, status=404)
#
#    # 确保用户有一个token
#    token, created = Token.objects.get_or_create(user=user)
#
#    # 返回带有token的成功登录消息
#    return JsonResponse({'status': 'success', 'message': f'Logged in as {user.wechat_nickname}', 'token': token.key})


