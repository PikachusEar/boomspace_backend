import uuid
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from datetime import datetime, timedelta
from .models import User, TimeSlot, Reservation, Court, Image, News, CourtCombo, isActivated, f_Image, f_News
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
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

def home(request):
    return HttpResponse("Hello, world. This is the API home page.")


@api_view(['GET'])
def wechat_login(request):
    js_code = request.GET.get('code')
    if not js_code:
        return JsonResponse({"message": "Invalid request. This URL only handles login requests"}, status=400)

    appid = 'wx2d3cffb19c8287b0'
    secret = '83c88699cf3df428baf0dcc44d64e8a2'
    url = f"https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={js_code}&grant_type=authorization_code"

    response = requests.get(url)
    data = response.json()

    if 'errcode' in data and data['errcode'] != 0:
        return JsonResponse({'status': 'error', 'message': f"微信登录失败: {data.get('errmsg', 'Unknown error')}"}, status=403)

    wechat_id = data.get('openid')
    wechat_nickname = 'WeChat User'

    # 查找或创建用户
    user, created = User.objects.get_or_create(
        wechat_id=wechat_id,
        defaults={
            'wechat_nickname': wechat_nickname,
            # 可以设置其他默认值
        }
    )

    # 如果是新用户，设置默认密码: "user_id+3470"
    if created:
        # user_id在首次save()时已生成，因此此时应已存在
        user.set_password(f"{user.user_id}3470")
        user.save()

    # 判断用户是否已注册email
    is_registered = bool(user.email)

    try:
        activation_status = isActivated.objects.first()
        is_activated = activation_status.is_activated if activation_status else True
    except isActivated.DoesNotExist:
        is_activated = True

    # 为用户创建或获取现有的Token
    token, _ = Token.objects.get_or_create(user=user)

    # 返回Token而不是进行重定向，同时添加is_registered字段
    return JsonResponse({
        'status': 'success',
        'message': '登录成功',
        'token': token.key,
        'is_new_user': created,
        'is_registered': is_registered,
        'is_activated': is_activated
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
    # 获取时间段ID列表和日期列表
    timeslot_ids = request.data.get('timeslot_ids', [])
    dates = request.data.get('dates', [])

    # 基本验证
    if not timeslot_ids or not dates:
        return JsonResponse({
            'status': 'error',
            'message': '请提供时间段ID列表和日期列表'
        }, status=400)

    if not isinstance(timeslot_ids, list) or not isinstance(dates, list):
        return JsonResponse({
            'status': 'error',
            'message': 'timeslot_ids和dates必须是列表格式'
        }, status=400)

    if len(timeslot_ids) != len(dates):
        return JsonResponse({
            'status': 'error',
            'message': '时间段ID列表和日期列表长度必须相同'
        }, status=400)

    try:
        # 解析所有日期并验证格式
        parsed_dates = []
        for date_str in dates:
            try:
                parsed_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
                parsed_dates.append(parsed_date)
            except ValueError:
                return JsonResponse({
                    'status': 'error',
                    'message': f'无效的日期格式: {date_str}'
                }, status=400)

        # 使用集合去重验证时间段是否存在
        unique_timeslot_ids = set(timeslot_ids)
        timeslots_qs = TimeSlot.objects.filter(
            id__in=unique_timeslot_ids
        ).select_related('court')

        # 验证所有请求的独特时间段ID是否都存在
        if timeslots_qs.count() != len(unique_timeslot_ids):
            return JsonResponse({
                'status': 'error',
                'message': 'Failed reservation: One or more time slots not exist'
            }, status=404)

        timeslots_dict = {str(slot.id): slot for slot in timeslots_qs}
        current_date = timezone.now().date()

        # 验证每个(包括重复ID的)时间段与日期的匹配和可预订性
        for timeslot_id, date in zip(timeslot_ids, parsed_dates):
            timeslot = timeslots_dict[str(timeslot_id)]

            # 验证时间范围
            days_ahead = (date - current_date).days
            if days_ahead < 0 or days_ahead > timeslot.court.timerange:
                return JsonResponse({
                    'status': 'error',
                    'message': f'时间段 {timeslot.court.name} 在 {date} 已超出可预订范围'
                }, status=400)

            # 验证星期几
            booking_weekday = date.isoweekday()  # 获取预订日期的星期几(1-7)
            if timeslot.day_of_week != 0 and timeslot.day_of_week != booking_weekday:
                # day_of_week为0表示每天都可预约
                return JsonResponse({
                    'status': 'error',
                    'message': f'时间段 {timeslot.court.name} 只能在星期{timeslot.day_of_week}预订，而{date}是星期{booking_weekday}'
                }, status=400)

        # 检查是否已有预定占用这些时间段
        reservation_conflicts = Reservation.objects.filter(
            Q(timeslot__in=timeslots_qs) &
            Q(date__in=parsed_dates) &
            (Q(status='pending') | Q(status='confirmed'))
        ).values('timeslot_id', 'date')

        if reservation_conflicts.exists():
            return JsonResponse({
                'status': 'error',
                'message': 'Failed reservation: One or more time slots have already been booked'
            }, status=400)

        # 计算总费用
        total_price = sum(timeslots_dict[str(tid)].price for tid in timeslot_ids)

        user = request.user

        # 检查用户余额是否充足
        if user.wallet_balance < total_price:
            return JsonResponse({
                'status': 'error',
                'message': 'Failed reservation: Insufficient account balance'
            }, status=400)

        # 创建所有预定
        reservations = []
        for timeslot_id, date in zip(timeslot_ids, parsed_dates):
            timeslot = timeslots_dict[str(timeslot_id)]
            reservation = Reservation.objects.create(
                user=user,
                timeslot=timeslot,
                date=date,
                price=timeslot.price,
                status='confirmed'
            )
            reservations.append(reservation)

        # 扣除总金额
        user.wallet_balance -= total_price
        user.save()

        # 返回成功信息及预订详情
        return JsonResponse({
            'status': 'success',
            'message': '预订成功，请在我的预定中查看预定详情',
            'total_price': str(total_price)
        })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'预订失败：{str(e)}'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def make_combo_reservation(request):
    # 从请求中获取时间段ID列表、日期列表和组合场地ID
    timeslot_ids = request.data.get('timeslot_ids', [])
    dates = request.data.get('dates', [])  # 改为接收日期列表
    combo_id = request.data.get('combo_id')

    # 基本验证
    if not timeslot_ids or not dates or not combo_id:
        return JsonResponse({
            'status': 'error',
            'message': '请提供时间段ID列表、日期列表和组合场地ID'
        }, status=400)

    if not isinstance(timeslot_ids, list) or not isinstance(dates, list):
        return JsonResponse({
            'status': 'error',
            'message': 'timeslot_ids和dates必须是列表格式'
        }, status=400)

    try:
        # 获取组合场地信息
        combo = CourtCombo.objects.get(id=combo_id, is_active=True)
        combo_courts = combo.combined_courts.filter(is_active=True)

        # 解析所有日期并验证格式
        parsed_dates = []
        for date_str in dates:
            try:
                parsed_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
                parsed_dates.append(parsed_date)
            except ValueError:
                return JsonResponse({
                    'status': 'error',
                    'message': f'无效的日期格式: {date_str}'
                }, status=400)

        # 获取时间段信息
        timeslots = TimeSlot.objects.filter(
            id__in=timeslot_ids,
            is_active=True,
            court__in=combo_courts
        ).select_related('court')

        # 验证时间段数量
        courts_count = combo_courts.count()
        if len(timeslots) != len(timeslot_ids) or len(timeslots) % courts_count != 0:
            return JsonResponse({
                'status': 'error',
                'message': '所选时间段不存在、不可用或数量不匹配'
            }, status=404)

        # 验证日期数量
        if len(parsed_dates) * courts_count != len(timeslot_ids):
            return JsonResponse({
                'status': 'error',
                'message': '日期数量与时间段组合不匹配'
            }, status=400)

        # 验证每个时间段的可用性、时间范围和星期几
        current_date = timezone.now().date()
        timeslots_dict = {str(slot.id): slot for slot in timeslots}

        for timeslot_id, date in zip(timeslot_ids, parsed_dates * courts_count):
            timeslot = timeslots_dict[str(timeslot_id)]

            # 验证时间范围
            days_ahead = (date - current_date).days
            if days_ahead < 0 or days_ahead > timeslot.court.timerange:
                return JsonResponse({
                    'status': 'error',
                    'message': f'时间段 {timeslot.court.name} 在 {date} 已超出可预订范围'
                }, status=400)

            # 验证星期几
            booking_weekday = date.isoweekday()
            if timeslot.day_of_week != 0 and timeslot.day_of_week != booking_weekday:
                return JsonResponse({
                    'status': 'error',
                    'message': f'时间段 {timeslot.court.name} 只能在星期{timeslot.day_of_week}预订，而{date}是星期{booking_weekday}'
                }, status=400)

        # 检查是否已有预定占用这些时间段
        reservation_conflicts = Reservation.objects.filter(
            Q(timeslot__in=timeslots) &
            Q(date__in=parsed_dates) &
            (Q(status='pending') | Q(status='confirmed'))
        ).exists()

        if reservation_conflicts:
            return JsonResponse({
                'status': 'error',
                'message': '预定失败：一个或多个时间段已被预订'
            }, status=400)

        # 计算总价格
        base_price_per_combo = sum(timeslot.price for timeslot in timeslots[:courts_count])
        total_base_price = base_price_per_combo * len(parsed_dates)

        if combo.fixed_price:
            total_price = combo.fixed_price * len(parsed_dates)
        elif combo.discount:
            total_price = round(total_base_price * Decimal(str(combo.discount)), 2)
        else:
            total_price = total_base_price

        user = request.user

        # 检查用户余额是否充足
        if user.wallet_balance < total_price:
            return JsonResponse({
                'status': 'error',
                'message': '预定失败，账户余额不足'
            }, status=400)

        # 扣除用户余额并保存
        user.wallet_balance -= total_price
        user.save()

        # 创建预订
        reservations = []
        individual_price = (total_price / len(timeslots)).quantize(Decimal('0.01'))

        for timeslot_id, date in zip(timeslot_ids, parsed_dates * courts_count):
            timeslot = timeslots_dict[str(timeslot_id)]
            reservation = Reservation.objects.create(
                user=user,
                timeslot=timeslot,
                date=date,
                price=individual_price,
                status='confirmed',
                is_combo=True
            )
            reservations.append(reservation)

        # 返回成功信息及预订详情
        return JsonResponse({
            'status': 'success',
            'message': '预订成功，请在我的预定中查看预定详情',
            'reservation_ids': [str(res.unique_id) for res in reservations],
            'total_price': str(total_price),
            'individual_price': str(individual_price)
        })

    except (CourtCombo.DoesNotExist, TimeSlot.DoesNotExist) as e:
        return JsonResponse({
            'status': 'error',
            'message': '所选组合场地或时间段不存在'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'预订失败：{str(e)}'
        }, status=500)




@api_view(['GET'])
@permission_classes([IsAuthenticated])
def view_reservations_and_balance(request):
    user = request.user  # 用户通过Token进行验证并通过Django的session获取

    # 获取用户的所有预定信息
    reservations = Reservation.objects.filter(user=user).values(
        'date', 'created_at', 'timeslot__start_time', 'timeslot__end_time', 'timeslot__court__name', 'status','unique_id'
    ).order_by('date', 'timeslot__start_time')

    # 准备预定信息
    reservations_data = [{
        'date': reservation['date'].strftime("%Y-%m-%d"),
        'created_at': localtime(reservation['created_at']).strftime("%Y-%m-%d %H:%M"),
        'start_time': reservation['timeslot__start_time'].strftime("%H:%M"),
        'end_time': reservation['timeslot__end_time'].strftime("%H:%M"),
        'court_name': reservation['timeslot__court__name'],
        'status': reservation['status'],
        'unique_id': reservation['unique_id'],
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
        'wallet_balance': user.wallet_balance,
        'user_id': user.user_id
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
    try:
        activation_status = isActivated.objects.first()
        is_activated = activation_status.is_activated if activation_status else True
    except isActivated.DoesNotExist:
        is_activated = True

    if is_activated:
        images = Image.objects.all()
        newses = News.objects.all()

    else:
        images = f_Image.objects.all()
        newses = f_News.objects.all()

    image_data = [
        {
            'image_url': request.build_absolute_uri(settings.MEDIA_URL + image.image.name),  # 需要配置
            'title': image.title,
            'description': image.description,
            'is_activated': is_activated,
        } for image in images
    ]

    news_data = [
        {
            'url': news.url,
            'title': news.title,
            'description': news.description,
            'image_url': request.build_absolute_uri(settings.MEDIA_URL + news.image.name),
            'poster_url': request.build_absolute_uri(settings.MEDIA_URL + news.poster.name)

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


@api_view(['POST'])
def web_login(request):
    """
    Web login endpoint that supports both email and phone authentication
    Accepts POST request with:
    {
        "username": "user@example.com" or "1234567890",
        "password": "password123"
    }
    """
    username = request.data.get('username')
    password = request.data.get('password')

    if not username or not password:
        return Response({
            'status': 'error',
            'message': 'Please provide both username and password'
        }, status=400)

    # Determine if username is email or phone
    try:
        validate_email(username)
        # If no ValidationError, this is an email
        user = User.objects.filter(email=username).first()
    except ValidationError:
        # If ValidationError, treat as phone number
        user = User.objects.filter(phone=username).first()

    if not user:
        return Response({
            'status': 'error',
            'message': 'Invalid username or password'
        }, status=404)

    # Verify password
    if not user.check_password(password):
        return Response({
            'status': 'error',
            'message': 'Invalid username or password'
        }, status=404)

    # Check activation status
    try:
        activation_status = isActivated.objects.first()
        is_activated = activation_status.is_activated if activation_status else True
    except isActivated.DoesNotExist:
        is_activated = True

    # Get or create token
    token, _ = Token.objects.get_or_create(user=user)

    # Check if user has completed registration (has both email and phone)
    is_registered = bool(user.email and user.phone)

    return Response({
        'status': 'success',
        'message': 'Login successful',
        'token': token.key,
        'is_new_user': False,  # Always false for web login
        'is_registered': is_registered,
        'is_activated': is_activated
    })


@api_view(['POST'])
def web_register(request):
    """
    Web registration endpoint that handles new user registration
    Accepts POST request with:
    {
        "email": "user@example.com",
        "phone": "1234567890",
        "password": "password123",
        "confirmPassword": "password123"
    }
    """
    email = request.data.get('email')
    phone = request.data.get('phone')
    password = request.data.get('password')
    confirm_password = request.data.get('confirmPassword')

    # Validate required fields
    if not all([email, phone, password, confirm_password]):
        return Response({
            'status': 'error',
            'message': 'Please provide all required fields'
        }, status=400)

    # Validate email format
    try:
        validate_email(email)
    except ValidationError:
        return Response({
            'status': 'error',
            'message': 'Invalid email format'
        }, status=400)

    # Validate phone format (basic validation)
    if not phone.isdigit() or len(phone) < 10:
        return Response({
            'status': 'error',
            'message': 'Invalid phone number format'
        }, status=400)

    # Check password match
    if password != confirm_password:
        return Response({
            'status': 'error',
            'message': 'Passwords do not match'
        }, status=400)

    # Check if email already exists
    if User.objects.filter(email=email).exists():
        return Response({
            'status': 'error',
            'message': 'Email already registered'
        }, status=400)

    # Check if phone already exists
    if User.objects.filter(phone=phone).exists():
        return Response({
            'status': 'error',
            'message': 'Phone number already registered'
        }, status=400)

    try:
        with transaction.atomic():
            # Create new user with temporary wechat_id
            temp_wechat_id = f'web_user_{uuid.uuid4().hex[:8]}'

            # Create user
            user = User.objects.create(
                wechat_id=temp_wechat_id,
                email=email,
                phone=phone,
                wechat_nickname=email.split('@')[0],  # Use email username as initial nickname
            )
            user.set_password(password)
            user.save()

            # Create token for the new user
            token, _ = Token.objects.get_or_create(user=user)

            # Get activation status
            try:
                activation_status = isActivated.objects.first()
                is_activated = activation_status.is_activated if activation_status else True
            except isActivated.DoesNotExist:
                is_activated = True

            return Response({
                'status': 'success',
                'message': 'Registration successful',
                'is_new_user': True,
                'is_registered': True,
                'is_activated': is_activated
            })

    except Exception as e:
        return Response({
            'status': 'error',
            'message': f'Registration failed: {str(e)}'
        }, status=500)