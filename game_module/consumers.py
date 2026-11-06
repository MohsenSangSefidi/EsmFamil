import asyncio
import random
from collections import defaultdict

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.db.models import F
from django.utils import timezone

from room_module.models import Room, Player
from room_module.consumers import ALLOWED_LETTERS
from .models import Round, Submission, Vote

# ================= ثابت‌ها =================
FIELD_ORDER = ['name', 'family', 'city', 'food', 'fruit', 'animal', 'body', 'object']
FIELD_LABELS = {
    'name': 'اسم',
    'family': 'فامیل',
    'city': 'شهر یا کشور',
    'food': 'غذا',
    'fruit': 'میوه و سبزیجات',
    'animal': 'حیوان',
    'body': 'اعضای بدن',
    'object': 'اشیا',
}

# قاعده‌ی حذف: تعداد رأی «حذف» برای صفر شدن امتیاز
MIN_REJECT_VOTES_TO_DELETE = 2  # «بیشتر از ۲» → 3

# ================= State سراسری =================
got_it_registry = defaultdict(set)
review_registry = {}
round_ending = set()


class GameConsumer(AsyncJsonWebsocketConsumer):

    # ---------------- Connect / Disconnect ----------------
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code']
        self.room_group_name = f'room_{self.room_code}'

        if not self.scope['session'].session_key:
            await self.close()
            return
        self.session_key = self.scope['session'].session_key

        room = await self.get_room(self.room_code)
        if not room:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.send_current_state(room)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # ---------------- Router ----------------
    async def receive_json(self, content, **kwargs):
        t = content.get('type')
        if t == 'i_got_it':
            await self.handle_i_got_it()
        elif t == 'i_finished':
            await self.handle_i_finished(
                content.get('words', {}),
                force=content.get('force', False),
            )
        elif t == 'vote_word':
            await self.handle_vote_word(
                content.get('submission_id'),
                content.get('vote'),
            )
        elif t == 'confirm_next_field':
            await self.handle_confirm_next_field()
        elif t == 'next_round':
            await self.handle_next_round()

    # =====================================================
    #  «فهمیدم»
    # =====================================================
    async def handle_i_got_it(self):
        room = await self.get_room(self.room_code)
        if not room or room.status != 'playing':
            return
        round_obj = await self.get_current_round(room)
        if not round_obj:
            return

        got_it_registry[room.code].add(self.session_key)
        players = await self.get_players(room)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'got_it_update',
                'count': len(got_it_registry[room.code]),
                'total': len(players),
            },
        )

        if len(got_it_registry[room.code]) >= len(players):
            got_it_registry[room.code].clear()
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'word_entry_started',
                    'letter': round_obj.letter,
                    'round_time': room.round_time,
                },
            )

    # =====================================================
    #  پایان راند + شروع داوری
    # =====================================================
    async def handle_i_finished(self, words, force=False):
        room = await self.get_room(self.room_code)
        if not room:
            return
        round_obj = await self.get_current_round(room)
        player = await self.get_player(room, self.session_key)
        if not round_obj or not player:
            return

        # ✅ اعتبارسنجی سمت سرور — فقط برای پایان دستی
        # (اگر force=True باشد یعنی تایمر تمام شد یا کسی دیگر راند را بست،
        #  پس نباید مانع شویم تا راند قفل نشود)
        if not force:
            missing = [f for f in FIELD_ORDER if not (words.get(f, '') or '').strip()]
            if missing:
                labels = '، '.join(FIELD_LABELS[f] for f in missing)
                await self.send_json({
                    'type': 'error',
                    'message': f'لطفاً همه فیلدها را پر کنید. خالی: {labels}',
                })
                return

        if words:
            await self.save_submissions(round_obj, player, words)

        if room.code in round_ending:
            return
        if room.status != 'playing':
            return

        round_ending.add(room.code)
        try:
            await self.end_round(room, round_obj, player)
            await self.update_room_status(room, 'review')

            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'round_ended', 'ended_by': player.name},
            )

            await asyncio.sleep(1.5)

            if room.code not in review_registry:
                await self.start_review(room, round_obj)
        finally:
            round_ending.discard(room.code)

    # =====================================================
    #  رأی دادن / پس گرفتن رأی / علامت تکراری (فقط هاست)
    # =====================================================
    async def handle_vote_word(self, submission_id, vote_action):
        """
        actions:
          'set_reject'      → افزودن رأی حذف   (فقط برای کلمات دیگران)
          'clear_reject'    → پس گرفتن رأی حذف (فقط برای کلمات دیگران)
          'set_duplicate'   → علامت تکراری     (فقط هاست — حتی روی کلمه‌ی خودش)
          'clear_duplicate' → برداشتن علامت    (فقط هاست — حتی روی کلمه‌ی خودش)
        """
        room = await self.get_room(self.room_code)
        if not room or room.status != 'review':
            return

        player = await self.get_player(room, self.session_key)
        submission = await self.get_submission(submission_id)
        if not player or not submission:
            return

        is_host = await self.is_host(room, self.session_key)
        is_own = submission.player_id == player.id

        # ۱) رأی حذف: هرگز روی کلمه‌ی خودت
        if vote_action in ('set_reject', 'clear_reject'):
            if is_own:
                return

        # ۲) علامت تکراری: فقط هاست (چه کلمه‌ی خودش، چه دیگران)
        if vote_action in ('set_duplicate', 'clear_duplicate'):
            if not is_host:
                await self.send_json({
                    'type': 'error',
                    'message': 'فقط هاست می‌تواند کلمه را تکراری علامت بزند',
                })
                return

        # ۳) اجرای عملیات
        if vote_action == 'set_reject':
            await self.save_vote(submission, player, 'reject')
        elif vote_action == 'clear_reject':
            await self.delete_vote(submission, player)
        elif vote_action == 'set_duplicate':
            await self.mark_duplicate(submission, True)
        elif vote_action == 'clear_duplicate':
            await self.mark_duplicate(submission, False)
        else:
            return

        # ---- بازمحاسبه‌ی وضعیت ----
        reject_count = await self.count_votes(submission, 'reject')
        is_rejected = reject_count >= MIN_REJECT_VOTES_TO_DELETE
        is_duplicate = await self.get_is_duplicate(submission)

        await self.set_is_accepted(submission, False if is_rejected else None)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'word_voted',
                'submission_id': submission.id,
                'actor_session': self.session_key,
                'action': vote_action,
                'reject_count': reject_count,
                'is_rejected': is_rejected,
                'is_duplicate': is_duplicate,
            },
        )

    # =====================================================
    #  تأیید جمعی برای فیلد بعدی
    # =====================================================
    async def handle_confirm_next_field(self):
        room = await self.get_room(self.room_code)
        if not room or room.status != 'review':
            return
        state = review_registry.get(room.code)
        if not state or state.get('advancing'):
            return

        player = await self.get_player(room, self.session_key)
        if not player:
            return

        if self.session_key in state['confirmed_players']:
            state['confirmed_players'].discard(self.session_key)
            confirmed = False
        else:
            state['confirmed_players'].add(self.session_key)
            confirmed = True

        players = await self.get_players(room)
        total = len(players)
        count = len(state['confirmed_players'])

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'field_confirm_update',
                'confirmed_count': count,
                'total': total,
                'session': self.session_key,
                'confirmed': confirmed,
            },
        )

        if count >= total:
            state['advancing'] = True
            await asyncio.sleep(0.5)
            await self.advance_review(room)

    # =====================================================
    #  راند بعدی
    # =====================================================
    async def handle_next_round(self):
        room = await self.get_room(self.room_code)
        if not room or room.status != 'scoring':
            return
        if not await self.is_host(room, self.session_key):
            await self.send_json({'type': 'error', 'message': 'فقط هاست'})
            return
        letter = await self.pick_letter(room)
        if not letter:
            await self.end_game(room)
            return
        await self.create_round(room, letter)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'letter_chosen',
                'letter': letter,
                'round_time': room.round_time,
            },
        )

    # =====================================================
    #  Flow داوری
    # =====================================================
    async def start_review(self, room, round_obj):
        await self.update_room_status(room, 'review')
        review_registry[room.code] = {
            'round_id': round_obj.id,
            'fields': list(FIELD_ORDER),
            'current_idx': 0,
            'confirmed_players': set(),
            'advancing': False,
        }
        await self.broadcast_current_field(room, round_obj)

    async def broadcast_current_field(self, room, round_obj):
        state = review_registry.get(room.code)
        if not state:
            return
        field = state['fields'][state['current_idx']]
        submissions = await self.get_submissions_for_field(round_obj, field)
        players = await self.get_players(room)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'review_field',
                'field': field,
                'field_label': FIELD_LABELS[field],
                'field_index': state['current_idx'],
                'total_fields': len(state['fields']),
                'submissions': submissions,
                'confirmed_count': len(state['confirmed_players']),
                'total_players': len(players),
            },
        )

    async def advance_review(self, room):
        state = review_registry.get(room.code)
        if not state:
            return
        state['current_idx'] += 1
        state['confirmed_players'] = set()
        state['advancing'] = False

        round_obj = await self.get_current_round(room)

        if state['current_idx'] >= len(state['fields']):
            await self.calculate_scores(round_obj)
            await self.update_room_status(room, 'scoring')
            scores = await self.get_scores(room)
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'scores_update', 'scores': scores},
            )
            review_registry.pop(room.code, None)
        else:
            await self.broadcast_current_field(room, round_obj)

    async def end_game(self, room):
        await self.update_room_status(room, 'ended')
        scores = await self.get_scores(room)
        winner = max(scores, key=lambda x: x['total_score'], default=None)
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'game_ended', 'scores': scores, 'winner': winner},
        )

    # =====================================================
    #  Group event handlers (server → client)
    # =====================================================
    async def got_it_update(self, event):
        await self.send_json({
            'type': 'got_it_update',
            'count': event['count'],
            'total': event['total'],
        })

    async def word_entry_started(self, event):
        await self.send_json({
            'type': 'word_entry_started',
            'letter': event['letter'],
            'round_time': event['round_time'],
        })

    async def letter_chosen(self, event):
        await self.send_json({
            'type': 'letter_chosen',
            'letter': event['letter'],
            'round_time': event['round_time'],
        })

    async def round_ended(self, event):
        await self.send_json({'type': 'round_ended', 'ended_by': event['ended_by']})

    async def review_field(self, event):
        await self.send_json({
            'type': 'review_field',
            'field': event['field'],
            'field_label': event['field_label'],
            'field_index': event['field_index'],
            'total_fields': event['total_fields'],
            'submissions': event['submissions'],
            'confirmed_count': event['confirmed_count'],
            'total_players': event['total_players'],
            'my_session': self.session_key,
        })

    async def word_voted(self, event):
        await self.send_json({
            'type': 'word_voted',
            'submission_id': event['submission_id'],
            'actor_session': event['actor_session'],
            'action': event['action'],
            'reject_count': event['reject_count'],
            'is_rejected': event['is_rejected'],
            'is_duplicate': event['is_duplicate'],
        })

    async def field_confirm_update(self, event):
        await self.send_json({
            'type': 'field_confirm_update',
            'confirmed_count': event['confirmed_count'],
            'total': event['total'],
            'session': event['session'],
            'confirmed': event['confirmed'],
        })

    async def scores_update(self, event):
        await self.send_json({'type': 'scores_update', 'scores': event['scores']})

    async def game_ended(self, event):
        await self.send_json({
            'type': 'game_ended',
            'scores': event['scores'],
            'winner': event['winner'],
        })

    # =====================================================
    #  ارسال وضعیت به بازیکن تازه‌وارد
    # =====================================================
    async def send_current_state(self, room):
        if room.status == 'playing':
            round_obj = await self.get_current_round(room)
            if round_obj:
                await self.send_json({
                    'type': 'letter_chosen',
                    'letter': round_obj.letter,
                    'round_time': room.round_time,
                })
        elif room.status == 'review':
            state = review_registry.get(room.code)
            round_obj = await self.get_current_round(room)
            if state and round_obj:
                field = state['fields'][state['current_idx']]
                submissions = await self.get_submissions_for_field(round_obj, field)
                players = await self.get_players(room)
                await self.send_json({
                    'type': 'review_field',
                    'field': field,
                    'field_label': FIELD_LABELS[field],
                    'field_index': state['current_idx'],
                    'total_fields': len(state['fields']),
                    'submissions': submissions,
                    'confirmed_count': len(state['confirmed_players']),
                    'total_players': len(players),
                    'my_session': self.session_key,
                })
        elif room.status == 'scoring':
            scores = await self.get_scores(room)
            await self.send_json({'type': 'scores_update', 'scores': scores})
        elif room.status == 'ended':
            scores = await self.get_scores(room)
            winner = max(scores, key=lambda x: x['total_score'], default=None)
            await self.send_json({'type': 'game_ended', 'scores': scores, 'winner': winner})

    # =====================================================
    #  DB helpers
    # =====================================================
    @database_sync_to_async
    def get_room(self, code):
        try:
            return Room.objects.get(code=code)
        except Room.DoesNotExist:
            return None

    @database_sync_to_async
    def get_player(self, room, session_key):
        try:
            return Player.objects.get(room=room, session_key=session_key)
        except Player.DoesNotExist:
            return None

    @database_sync_to_async
    def get_current_round(self, room):
        return room.rounds.order_by('-started_at').first()

    @database_sync_to_async
    def get_players(self, room):
        return list(room.players.all())

    @database_sync_to_async
    def save_submissions(self, round_obj, player, words):
        for field_name, value in words.items():
            if field_name not in FIELD_ORDER:
                continue
            Submission.objects.update_or_create(
                round=round_obj,
                player=player,
                field_name=field_name,
                defaults={'value': (value or '').strip(), 'is_accepted': None},
            )

    @database_sync_to_async
    def get_submission(self, submission_id):
        try:
            return Submission.objects.select_related('player').get(id=submission_id)
        except Submission.DoesNotExist:
            return None

    @database_sync_to_async
    def save_vote(self, submission, voter, vote):
        Vote.objects.update_or_create(
            submission=submission,
            voter=voter,
            defaults={'vote': vote},
        )

    @database_sync_to_async
    def delete_vote(self, submission, voter):
        submission.votes.filter(voter=voter).delete()

    @database_sync_to_async
    def count_votes(self, submission, vote_type):
        return submission.votes.filter(vote=vote_type).count()

    @database_sync_to_async
    def get_is_duplicate(self, submission):
        return bool(
            Submission.objects.filter(id=submission.id)
            .values_list('is_duplicate', flat=True).first()
        )

    @database_sync_to_async
    def mark_duplicate(self, submission, value):
        Submission.objects.filter(id=submission.id).update(is_duplicate=value)

    @database_sync_to_async
    def set_is_accepted(self, submission, value):
        Submission.objects.filter(id=submission.id).update(is_accepted=value)

    @database_sync_to_async
    def get_submissions_for_field(self, round_obj, field_name):
        subs = (
            Submission.objects
            .filter(round=round_obj, field_name=field_name)
            .select_related('player')
            .prefetch_related('votes__voter')
            .order_by('player__joined_at')
        )
        result = []
        for s in subs:
            votes = [
                {'voter': v.voter.session_key, 'vote': v.vote}
                for v in s.votes.all()
            ]
            result.append({
                'id': s.id,
                'player_name': s.player.name,
                'player_session': s.player.session_key,
                'value': s.value,
                'is_accepted': s.is_accepted,
                'is_duplicate': s.is_duplicate,
                'reject_count': sum(1 for v in votes if v['vote'] == 'reject'),
                'votes': votes,
            })
        return result

    @database_sync_to_async
    def update_room_status(self, room, status):
        room.status = status
        room.save(update_fields=['status'])

    @database_sync_to_async
    def end_round(self, room, round_obj, player):
        round_obj.ended_at = timezone.now()
        round_obj.ended_by_player = player
        round_obj.save(update_fields=['ended_at', 'ended_by_player'])

    @database_sync_to_async
    def is_host(self, room, session_key):
        return room.host_session == session_key

    @database_sync_to_async
    def pick_letter(self, room):
        remaining = [l for l in ALLOWED_LETTERS if l not in (room.used_letters or [])]
        if not remaining:
            return None
        letter = random.choice(remaining)
        room.current_letter = letter
        room.used_letters = list(room.used_letters or []) + [letter]
        room.current_round += 1
        room.save()
        return letter

    @database_sync_to_async
    def create_round(self, room, letter):
        Round.objects.create(room=room, letter=letter)
        room.status = 'playing'
        room.save(update_fields=['status'])

    # =====================================================
    #  امتیازدهی
    # =====================================================
    @database_sync_to_async
    def calculate_scores(self, round_obj):
        """
        کلمه‌ی حذف‌شده (is_accepted=False) حتی اگر تکراری باشد → 0
        کلمه‌ی تکراری (is_duplicate=True) و حذف‌نشده → 5
        کلمه‌ی معتبر یکتا → 10
        """
        if round_obj.is_scored:
            return

        submissions = Submission.objects.filter(round=round_obj)
        player_scores = defaultdict(int)

        for sub in submissions:
            v = (sub.value or '').strip()
            if not v or sub.is_accepted is False:
                score = 0
            elif sub.is_duplicate:
                score = 5
            else:
                score = 10
            player_scores[sub.player_id] += score

        for pid, score in player_scores.items():
            Player.objects.filter(id=pid).update(total_score=F('total_score') + score)

        round_obj.is_scored = True
        round_obj.save(update_fields=['is_scored'])

    @database_sync_to_async
    def get_scores(self, room):
        players = room.players.all().order_by('-total_score', 'joined_at')
        return [
            {'name': p.name, 'total_score': p.total_score, 'is_host': p.is_host}
            for p in players
        ]
