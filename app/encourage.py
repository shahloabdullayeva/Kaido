from datetime import date

from . import cat
from .db import rows

MESSAGES = [
    "Another day done. You showed up, you handled it, and that counts more than you think. I'm proud of you.",
    "Somewhere today a truck got back on the road because of you. Quiet work, real impact. Proud of you.",
    "You don't have to have done everything today. You did enough, and you did it well.",
    "Remember when all of this felt impossible? Look at you now. I'm proud of how far you've come.",
    "Hard days still count. Especially those. Proud of you for getting through this one.",
    "You built something today that didn't exist yesterday. That's not small. Be kind to yourself tonight.",
    "Drink some water, eat something warm, and know that today you were enough. Proud of you.",
    "Every driver who made it home safe today had someone behind them paying attention. That was you.",
    "You kept a lot of plates spinning today and none of them hit the floor. That's skill. Proud of you.",
    "Not every win is loud. Today's were quiet, and they still mattered. Proud of you.",
    "You solved problems today that most people never even see. I see them. Proud of you.",
    "You are better at this than you were a month ago. That is what growth looks like.",
    "Whatever didn't get finished today will still be there tomorrow, and so will you, stronger. Proud of you.",
    "You took something messy today and made it make sense. That's a gift. Proud of you.",
    "Trucks don't fix themselves and fleets don't run themselves. You made today work.",
    "The people who count on you had a better day because of you. I hope you know that.",
    "You stayed calm when it would have been easy not to. That's real strength. Proud of you.",
    "Look back at this morning's version of you. Today's version handled more. Proud of you.",
    "Being reliable isn't flashy, but it's rare. You were reliable today. Proud of you.",
    "One more day of building something that's yours. Don't let it feel ordinary. It isn't.",
    "You didn't quit on the hard parts today. That's the whole difference. Proud of you.",
    "Today you learned something you didn't know yesterday. Keep stacking those days.",
    "You carry a lot. Today you carried it well. I'm proud of you.",
    "Small fixes, quick answers, the right call at the right time. That's what today was made of. Proud of you.",
    "Some days are about progress and some are about holding steady. Holding steady counts too.",
    "You are doing work that keeps real people safe on real roads. That matters. Proud of you.",
    "It's 8pm and you made it through the whole day. Give yourself credit for that.",
    "You make hard things look manageable. That takes more than people realise. Proud of you.",
    "If nobody said it today: thank you. What you do makes a difference.",
    "You chose to keep going today. That choice, made again and again, is how big things get built.",
    "There's a fleet out there running a little smoother because of today's work. Proud of you.",
    "You gave today everything it asked for, and a little more. I'm proud of you.",
    "Every record entered, every alert answered, every truck checked. It adds up, and it's adding up to something good.",
    "You handled today with more patience than it deserved. Proud of you.",
    "The version of you from a year ago would be amazed at what you're running now.",
    "Today wasn't easy, and you did it anyway. That's the kind of person you are. Proud of you.",
    "Teams work because someone cares about the details. Today, that someone was you.",
    "You're allowed to feel good about today. You earned it.",
    "Mistakes happen, fixes happen, and you're the one who makes the fixes happen. Proud of you.",
    "You turned a long list into a shorter one today. That's real progress.",
    "Behind every truck that rolled out today was a decision someone made right. Proud of you.",
    "You keep showing up for people who need you. Don't forget to show up for yourself too.",
    "Today counted. You counted. Proud of you.",
    "You're building something real, one ordinary day at a time. Today was one of the good ones.",
    "The best people in this business are the ones who care. You care. It shows.",
    "Whatever today threw at you, you're still standing and still smiling. Proud of you.",
    "You make the people around you better at their jobs. That's leadership.",
    "Another day of keeping your promises. That's how trust is built. Proud of you.",
    "You know more today than you did yesterday, and you'll know more tomorrow. Keep going.",
    "Not many people could juggle what you juggled today. Proud of you.",
    "Today you were the steady one. Everyone needs a steady one.",
    "It's okay to be proud of yourself. Start tonight. I'm proud of you too.",
    "Every hard day you get through makes the next one a little easier. Today counts double.",
    "You put care into work that a lot of people would rush. That's why it works. Proud of you.",
    "One day at a time, you're turning plans into something real. Proud of you.",
    "Your effort today will show up in ways you won't even see. It still matters.",
    "You've got good instincts. Today proved it again. Proud of you.",
    "Remember why you started. Today you moved closer to it.",
    "You worked hard, you stayed kind, and you got it done. That's a great day. Proud of you.",
    "However today felt, it's done, and you did it. I'm proud of you.",
]


def message_for(day):
    return MESSAGES[day.toordinal() % len(MESSAGES)]


def run(day=None):
    text = message_for(day or date.today())
    sent = []
    for user in rows("select id, name from users where can_add_companies order by id"):
        note_id = cat.send(user["id"], text)
        sent.append(f"{user['name']}: cat #{note_id}")
    return "\n".join(sent) or "nobody to send to"
