from django.db import models
from room_module.models import Room, Player


class Round(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='rounds')
    letter = models.CharField(max_length=2)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by_player = models.ForeignKey(
        Player, on_delete=models.SET_NULL, null=True, blank=True
    )
    is_scored = models.BooleanField(default=False)

    def __str__(self):
        return f"Round {self.id} - Letter {self.letter}"


class Submission(models.Model):
    FIELD_CHOICES = [
        ('name', 'اسم'),
        ('family', 'فامیل'),
        ('city', 'شهر یا کشور'),
        ('food', 'غذا'),
        ('fruit', 'میوه و سبزیجات'),
        ('animal', 'حیوان'),
        ('body', 'اعضای بدن'),
        ('object', 'اشیا'),
    ]
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='submissions')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='submissions')
    field_name = models.CharField(max_length=20, choices=FIELD_CHOICES)
    value = models.CharField(max_length=100, blank=True)

    is_accepted = models.BooleanField(null=True, blank=True)

    # اگر تکراری بودن کلمه رأی بیاورد و حذف نشود → امتیاز 5
    is_duplicate = models.BooleanField(default=False)

    class Meta:
        unique_together = ('round', 'player', 'field_name')


class Vote(models.Model):
    VOTE_CHOICES = [
        ('reject', 'حذف'),
        ('duplicate', 'تکراری'),
    ]
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='votes')
    voter = models.ForeignKey(Player, on_delete=models.CASCADE)
    vote = models.CharField(max_length=10, choices=VOTE_CHOICES)

    class Meta:
        unique_together = ('submission', 'voter')
