from django.shortcuts import render, redirect
from django.utils.crypto import get_random_string
from .models import Room, Player


def index(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            return render(request, 'index.html', {'error': 'نام نمایشی الزامی است'})

        # ذخیره نام در session
        request.session['player_name'] = name

        if not request.session.session_key:
            request.session.create()

        action = request.POST.get('action')
        if action == 'create':
            # ایجاد اتاق جدید
            room = Room.objects.create(host_session=request.session.session_key)
            Player.objects.create(
                room=room,
                session_key=request.session.session_key,
                name=name,
                is_host=True,
            )
            return redirect('room', room_code=room.code)
        elif action == 'join':
            code = request.POST.get('room_code', '').strip()
            try:
                room = Room.objects.get(code=code)
            except Room.DoesNotExist:
                return render(request, 'index.html', {'error': 'اتاق یافت نشد'})

            # بررسی وجود بازیکن در اتاق
            if not Player.objects.filter(room=room, session_key=request.session.session_key).exists():
                Player.objects.create(
                    room=room,
                    session_key=request.session.session_key,
                    name=name,
                )
            return redirect('room', room_code=room.code)

    return render(request, 'index.html')


def room_view(request, room_code):
    """صفحه لابی اتاق"""
    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        return redirect('index')

    # بررسی عضویت
    if not Player.objects.filter(room=room, session_key=request.session.session_key).exists():
        return redirect('index')

    return render(request, 'room.html', {'room': room})


def game_view(request, room_code):
    """صفحه بازی"""
    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        return redirect('index')

    if not Player.objects.filter(room=room, session_key=request.session.session_key).exists():
        return redirect('index')

    return render(request, 'game.html', {'room': room})
