import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Room, Player
import random

ALLOWED_LETTERS = list("آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")


class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code']
        self.room_group_name = f'room_{self.room_code}'

        if not self.scope['session'].session_key:
            await self.close()
            return

        self.session_key = self.scope['session'].session_key

        # بررسی وجود اتاق
        room = await self.get_room(self.room_code)
        if not room:
            await self.close()
            return

        # پیوستن به گروه
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        # افزودن بازیکن به اتاق (اگر قبلاً نبوده)
        player = await self.get_or_create_player(room, self.session_key)
        await self.send_room_update()

    async def disconnect(self, close_code):
        # حذف بازیکن از اتاق (فقط در لابی)
        if self.room_code:
            room = await self.get_room(self.room_code)
            if room and room.status == 'lobby':
                await self.remove_player(room, self.session_key)
                await self.send_room_update()
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        event_type = content.get('type')
        if event_type == 'player_ready':
            await self.handle_player_ready(content.get('is_ready', True))
        elif event_type == 'set_round_time':
            await self.handle_set_round_time(content.get('round_time'))
        elif event_type == 'start_game':
            await self.handle_start_game()

    # ------------------- Handlerها -------------------
    async def handle_player_ready(self, is_ready):
        room = await self.get_room(self.room_code)
        if not room or room.status != 'lobby':
            return
        await self.set_player_ready(room, self.session_key, is_ready)
        await self.send_room_update()
        # بررسی آماده بودن همه
        all_ready = await self.check_all_ready(room)
        if all_ready:
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'all_ready', 'message': 'همه بازیکنان آماده‌اند'}
            )

    async def handle_set_round_time(self, round_time):
        if not (30 <= round_time <= 120):
            return
        room = await self.get_room(self.room_code)
        if not room:
            return
        # فقط هاست می‌تواند زمان را تغییر دهد
        if not await self.is_host(room, self.session_key):
            return
        await self.update_room_round_time(room, round_time)
        await self.send_room_update()

    async def handle_start_game(self):
        room = await self.get_room(self.room_code)
        if not room or room.status != 'lobby':
            return
        if not await self.is_host(room, self.session_key):
            return
        if not await self.check_all_ready(room):
            await self.send_json({'type': 'error', 'message': 'همه بازیکنان آماده نیستند'})
            return

        # انتخاب حرف تصادفی
        letter = await self.pick_letter(room)
        if not letter:
            await self.send_json({'type': 'error', 'message': 'حرفی باقی نمانده'})
            return

        # به‌روزرسانی وضعیت اتاق
        await self.start_game_db(room, letter)

        # اطلاع به همه
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'game_started',
                'letter': letter,
                'round_time': room.round_time,
            }
        )

    # ------------------- ارسال به گروه -------------------
    async def send_room_update(self):
        room = await self.get_room(self.room_code)
        if not room:
            return
        players = await self.get_players(room)
        data = {
            'type': 'room_update',
            'players': players,
            'host_session': room.host_session,
            'round_time': room.round_time,
            'status': room.status,
        }
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'room_update_handler', 'data': data}
        )

    async def room_update_handler(self, event):
        await self.send_json(event['data'])

    async def all_ready(self, event):
        await self.send_json({'type': 'all_ready', 'message': event['message']})

    async def game_started(self, event):
        await self.send_json({
            'type': 'game_started',
            'letter': event['letter'],
            'round_time': event['round_time'],
        })

    # ------------------- توابع دیتابیس -------------------
    @database_sync_to_async
    def get_room(self, code):
        try:
            return Room.objects.get(code=code)
        except Room.DoesNotExist:
            return None

    @database_sync_to_async
    def get_or_create_player(self, room, session_key):
        player, _ = Player.objects.get_or_create(
            room=room,
            session_key=session_key,
            defaults={'name': 'بازیکن', 'is_host': (room.host_session == session_key)}
        )
        return player

    @database_sync_to_async
    def remove_player(self, room, session_key):
        Player.objects.filter(room=room, session_key=session_key).delete()

    @database_sync_to_async
    def get_players(self, room):
        return list(room.players.values('name', 'is_ready', 'is_host', 'total_score'))

    @database_sync_to_async
    def set_player_ready(self, room, session_key, is_ready):
        Player.objects.filter(room=room, session_key=session_key).update(is_ready=is_ready)

    @database_sync_to_async
    def check_all_ready(self, room):
        players = room.players.all()
        return players.exists() and all(p.is_ready for p in players)

    @database_sync_to_async
    def is_host(self, room, session_key):
        return room.host_session == session_key

    @database_sync_to_async
    def update_room_round_time(self, room, round_time):
        room.round_time = round_time
        room.save()

    @database_sync_to_async
    def pick_letter(self, room):
        remaining = [l for l in ALLOWED_LETTERS if l not in room.used_letters]
        if not remaining:
            return None
        letter = random.choice(remaining)
        room.current_letter = letter
        room.used_letters.append(letter)
        room.current_round += 1
        room.save()
        return letter

    @database_sync_to_async
    def start_game_db(self, room, letter):
        room.status = 'playing'
        room.current_letter = letter
        room.current_round += 1
        if letter not in room.used_letters:
            room.used_letters.append(letter)
        room.save()
        # ایجاد راند جدید
        from game_module.models import Round
        Round.objects.create(room=room, letter=letter)
