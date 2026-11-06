from django.db import models
import random
import string


def generate_room_code():
    """تولید کد ۶ رقمی یکتا برای اتاق"""
    while True:
        code = ''.join(random.choices(string.digits, k=6))
        if not Room.objects.filter(code=code).exists():
            return code


class Room(models.Model):
    STATUS_CHOICES = [
        ('lobby', 'Lobby'),
        ('playing', 'Playing'),
        ('review', 'Review'),
        ('scoring', 'Scoring'),
        ('ended', 'Ended'),
    ]
    code = models.CharField(max_length=6, unique=True, default=generate_room_code)
    host_session = models.CharField(max_length=40)  # session_key هاست
    round_time = models.PositiveIntegerField(default=60)  # ثانیه
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='lobby')
    used_letters = models.JSONField(default=list)  # حروف استفاده‌شده
    current_letter = models.CharField(max_length=2, blank=True, null=True)
    current_round = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Room {self.code} ({self.status})"


class Player(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='players')
    session_key = models.CharField(max_length=40)
    name = models.CharField(max_length=50)
    is_ready = models.BooleanField(default=False)
    is_host = models.BooleanField(default=False)
    total_score = models.IntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('room', 'session_key')

    def __str__(self):
        return f"{self.name} in {self.room.code}"
