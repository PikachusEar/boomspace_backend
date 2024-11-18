# Gym Reservation System

## 项目介绍
Gym Reservation System 是一个为健身房预约篮球场地而设计的微信小程序，旨在为用户提供一个便捷的在线预约体验。通过这个系统，用户可以查看可用的篮球场地，根据场地的时间段进行预约，管理自己的预约，并查看预约历史。

## 功能特点
- **用户登录**: 支持微信登录，确保用户信息安全。
- **查看场地**: 用户可以查看所有可用的篮球场地及其时间段。
- **预约场地**: 用户可以根据需求预约特定时间段的篮球场地。
- **管理预约**: 用户可以查看和取消自己的预约。

## 技术栈
- **后端**: Django + Django REST Framework
- **数据库**: MySQL
- **前端**: 微信小程序

## 更新
- **1118**: 更改了后台管理界面和首页的Title
- **1115**: 在admin的管理后台添加了"recharge"功能，方便为用户进行充值，每次充值生成充值记录方便财务管理
- **...**:
- **0826**: 添加了"get_images" api，返回swiper和news的图片url和文本，需提前配置Nginx代理服务器以对静态图片进行响应，完成Nginx配置后需要对"/api/views.py"的相应代码段进行修改
- **0817**: 添加了"view_user_info", "update_user_info"两个新api视图，添加了"Image"和"News"两个新model用于前端的首页展示
- **0815**: 对"wechat_login"的小程序前端进行了适配，配置了新的测试号appid & secret，添加了"is_new_user"的布尔值以便于发布小程序发布欢迎信息，完成了新用户和老用户的登陆验证功能(返回微信官方服务器的openid并进行保存)
- **0805**: 重构了make_reservation视图，以适应新的availiable_timeslots业务逻辑，添加了新的"view_reservations_and_balance" 功能：提供用户token，返回用户所有的reservation信息和钱包余额。引入了"SimpleUI"开源库优化Django Admin操作界面，相应"requirements.txt"依赖表进行了更新
- **0804**: 为所有的reservation订单添加了uuid方便追踪, 更新了availiable_timeslots的业务逻辑, 为"Court"新加入"timerange"键, 现在可以根据"timerange"的值自定义可查看最远预约时间, 并对可用时间段逻辑进行了优化
- **0731**: 更新了认证方式，从传统cookie转换为更适合小程序的token认证方法，对数据库结构进行了调整，如有必要请删除原有数据库重新创建
- **0726**: 更新"make_reservation"接口(POST)，通过"available_timeslots"返回的数据进行选择，加入钱包余额的检查和扣费
- **0724**: 更新"available_timeslots"接口(GET)，获取可用的空位表，去除带有"confirmed"和"pending"位置，只显示无人预定的空位
- **0720**: 初次更新Git

## To Do
- **用户其他信息的获取，新界面"我的账户"，开发"update_user_info"的api(0817Update已添加)**
- **Token的有效期配置，微信官方文档的有效期为2小时(是否有必要为2小时？)**
- **广告swiper和新闻栏的api支持(0826Update已添加)**


## Deployment
 - **for Ubuntu Server 24.04 LTS**
 - 安装依赖
 - sudo apt install python3-venv
 - sudo apt install git
 - sudo apt-get install pkg-config python3-dev default-libmysqlclient-dev build-essential
 - sudo apt-get install python3-dev default-libmysqlclient-dev build-essential
 - (venv) pip install -r requirements.txt
 - Nginx权限：需要chmod 755 static* and media*，否则403


## Nginx配置
 - 在 /etc/nginx/sites-available/default 使用如下代码

```basic
server {

    listen 80;

    server_name 192.168.248.128;

    client_max_body_size 15M;


    

    location /static/ {

        alias  /home/pikachu/api/GymReservation/static/;  
	autoindex on;
    }





    location /media/ {

        alias  /home/pikachu/api/GymReservation/media/;  
	autoindex on;
    }





    location / {

        proxy_pass http://0.0.0.0:8000;  

        proxy_set_header Host $host;

        proxy_set_header X-Real-IP $remote_addr;

        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        proxy_set_header X-Forwarded-Proto $scheme;

    }



    # Error handling

    error_page 500 502 503 504 /50x.html;

    location = /50x.html {

        root /usr/share/nginx/html;

    }

}

```
