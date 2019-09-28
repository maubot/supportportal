# supportportal
A [maubot](https://github.com/maubot/maubot) to manage customer support on Matrix.

The bot acts as the primary customer support user on Matrix who is invited by
users. When the bot is invited, it'll join and announce the invite to a
management room, where one of your customer support agents can claim the task
by joining the room.

Designed to work with bridges such as [mautrix-twilio](https://github.com/tulir/mautrix-twilio)
and [mautrix-telegram](https://github.com/tulir/mautrix-telegram), although it
works fine for a Matrix-native customer support system as well.
