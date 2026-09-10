import re
import random
from datetime import timedelta, datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from appeals import AppealStartButton

TIME_REGEX = re.compile(r"^(\d+)(s|m|h|d|w)$")
INVITE_REGEX = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)", re.IGNORECASE)


def parse_time(value: str) -> int | None:
    match = TIME_REGEX.match(value.strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return amount * multipliers[unit]


def can_moderate(guild: discord.Guild, moderator: discord.Member, target: discord.Member) -> bool:
    if moderator.id == guild.owner_id:
        return True
    if target.id == guild.owner_id:
        return False
    if target.top_role.position >= moderator.top_role.position:
        return False
    return True


async def dm_sanction(bot, member: discord.Member, guild: discord.Guild, action: str, reason: str, duration: str | None = None):
    embed = discord.Embed(
        title=f"Notificación de {action}",
        description=f"Fuiste sancionado en **{guild.name}**.",
        color=bot.embed_color,
    )
    embed.add_field(name="Razón", value=reason or "No especificada", inline=False)
    if duration:
        embed.add_field(name="Duración", value=duration, inline=False)
    embed.set_footer(text="Staff Team")
    view = None
    if action.lower() == "baneo":
        view = AppealStartButton(guild.id, member.id)
    try:
        await member.send(embed=embed, view=view)
    except discord.Forbidden:
        pass


class BotConfigState:
    def __init__(self, guild_id: int, existing: dict | None):
        self.guild_id = guild_id
        self.log_channel_id = existing.get("log_channel_id") if existing else None
        self.staff_roles = existing.get("staff_roles", []) if existing else []
        self.admin_roles = existing.get("admin_roles", []) if existing else []
        self.anti_invite = existing.get("anti_invite", False) if existing else False
        self.anti_flood = existing.get("anti_flood", True) if existing else True
        self.flood_limit = existing.get("flood_limit", 5) if existing else 5
        self.flood_seconds = existing.get("flood_seconds", 5) if existing else 5


class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view):
        super().__init__(placeholder="Canal de logs", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.log_channel_id = self.values[0].id
        await self.view_ref.refresh(interaction)


class StaffRoleSelect(discord.ui.RoleSelect):
    def __init__(self, view):
        super().__init__(placeholder="Roles de Staff", min_values=0, max_values=10)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.staff_roles = [r.id for r in self.values]
        await self.view_ref.refresh(interaction)


class AdminRoleSelect(discord.ui.RoleSelect):
    def __init__(self, view):
        super().__init__(placeholder="Roles de Admin/Owner", min_values=0, max_values=10)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.admin_roles = [r.id for r in self.values]
        await self.view_ref.refresh(interaction)


class BotSetupView(discord.ui.View):
    def __init__(self, bot, state: BotConfigState):
        super().__init__(timeout=600)
        self.bot = bot
        self.state = state
        self.add_item(LogChannelSelect(self))
        self.add_item(StaffRoleSelect(self))
        self.add_item(AdminRoleSelect(self))

    def build_preview(self) -> discord.Embed:
        embed = discord.Embed(title="Vista previa — Configuración del Bot", color=self.bot.embed_color)
        embed.add_field(name="Canal de logs", value=f"<#{self.state.log_channel_id}>" if self.state.log_channel_id else "No configurado", inline=False)
        embed.add_field(name="Roles de Staff", value=" ".join(f"<@&{r}>" for r in self.state.staff_roles) or "Ninguno", inline=False)
        embed.add_field(name="Roles de Admin/Owner", value=" ".join(f"<@&{r}>" for r in self.state.admin_roles) or "Ninguno", inline=False)
        embed.add_field(name="Anti-invite", value="Activado" if self.state.anti_invite else "Desactivado")
        embed.add_field(name="Anti-flood", value=f"{'Activado' if self.state.anti_flood else 'Desactivado'} ({self.state.flood_limit} msj / {self.state.flood_seconds}s)")
        embed.set_footer(text=self.bot.footer_text)
        return embed

    async def refresh(self, interaction: discord.Interaction):
        embed = self.build_preview()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Toggle Anti-Invite", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.anti_invite = not self.state.anti_invite
        await self.refresh(interaction)

    @discord.ui.button(label="Toggle Anti-Flood", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_flood(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.anti_flood = not self.state.anti_flood
        await self.refresh(interaction)

    @discord.ui.button(label="Guardar", style=discord.ButtonStyle.success, row=4)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = {
            "log_channel_id": self.state.log_channel_id,
            "staff_roles": self.state.staff_roles,
            "admin_roles": self.state.admin_roles,
            "anti_invite": self.state.anti_invite,
            "anti_flood": self.state.anti_flood,
            "flood_limit": self.state.flood_limit,
            "flood_seconds": self.state.flood_seconds,
        }
        await self.bot.db.guild_config.update_one({"guild_id": self.state.guild_id}, {"$set": data}, upsert=True)
        self.bot.guild_config_cache[self.state.guild_id] = data
        embed = discord.Embed(description=f"{self.bot.custom_emojis['aceptar']} Configuración guardada.", color=self.bot.embed_color)
        embed.set_footer(text=self.bot.footer_text)
        await interaction.response.edit_message(embed=embed, view=None)


class GiveawayJoinView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.join.custom_id = f"dbb_giveaway_join:{giveaway_id}"

    @discord.ui.button(label="Participar", emoji="🎉", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        from bson import ObjectId
        bot = interaction.client
        gw = await bot.db.giveaways.find_one({"_id": ObjectId(self.giveaway_id)})
        if not gw or gw["status"] != "running":
            await interaction.response.send_message("Este giveaway ya finalizó.", ephemeral=True)
            return
        if interaction.user.id in gw.get("participants", []):
            await bot.db.giveaways.update_one({"_id": ObjectId(self.giveaway_id)}, {"$pull": {"participants": interaction.user.id}})
            await interaction.response.send_message("Te saliste del giveaway.", ephemeral=True)
        else:
            await bot.db.giveaways.update_one({"_id": ObjectId(self.giveaway_id)}, {"$addToSet": {"participants": interaction.user.id}})
            await interaction.response.send_message("¡Ahora estás participando!", ephemeral=True)


async def end_giveaway(bot, giveaway_id, reroll: bool = False):
    from bson import ObjectId
    gw = await bot.db.giveaways.find_one({"_id": ObjectId(giveaway_id)})
    if not gw:
        return None
    channel = bot.get_channel(gw["channel_id"])
    participants = gw.get("participants", [])
    winners_count = gw["winners"]
    winners = random.sample(participants, min(winners_count, len(participants))) if participants else []

    if not reroll:
        await bot.db.giveaways.update_one({"_id": ObjectId(giveaway_id)}, {"$set": {"status": "ended", "winners_result": winners}})
    else:
        await bot.db.giveaways.update_one({"_id": ObjectId(giveaway_id)}, {"$set": {"winners_result": winners}})

    if channel:
        if winners:
            mentions = ", ".join(f"<@{w}>" for w in winners)
            embed = discord.Embed(
                title="🎉 Giveaway finalizado" if not reroll else "🎉 Giveaway - Reroll",
                description=f"Premio: **{gw['prize']}**\nGanador(es): {mentions}",
                color=bot.embed_color,
            )
        else:
            embed = discord.Embed(
                title="🎉 Giveaway finalizado",
                description=f"Premio: **{gw['prize']}**\nNadie participó.",
                color=bot.embed_color,
            )
        embed.set_footer(text=bot.footer_text)
        await channel.send(embed=embed)

    for w in winners:
        member = channel.guild.get_member(w) if channel else None
        if member:
            try:
                dm_embed = discord.Embed(
                    description=f"¡Felicidades! Ganaste **{gw['prize']}** en {channel.guild.name}.",
                    color=bot.embed_color,
                )
                dm_embed.set_footer(text=bot.footer_text)
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass
    return winners


class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.giveaway_checker.start()

    def cog_unload(self):
        self.giveaway_checker.cancel()

    async def cog_load(self):
        configs = self.bot.db.guild_config.find({})
        async for c in configs:
            self.bot.guild_config_cache[c["guild_id"]] = c
        running = self.bot.db.giveaways.find({"status": "running"})
        async for gw in running:
            self.bot.add_view(GiveawayJoinView(str(gw["_id"])))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        config = self.bot.guild_config_cache.get(message.guild.id)
        if not config:
            config = await self.bot.db.guild_config.find_one({"guild_id": message.guild.id})
            if config:
                self.bot.guild_config_cache[message.guild.id] = config
        if not config:
            await self.bot.process_commands(message)
            return

        staff_roles = set(config.get("staff_roles", [])) | set(config.get("admin_roles", []))
        is_staff = any(r.id in staff_roles for r in getattr(message.author, "roles", []))

        if not is_staff and config.get("anti_invite") and INVITE_REGEX.search(message.content):
            await message.delete()
            warning = await message.channel.send(f"{message.author.mention} no se permiten invitaciones de Discord aquí.")
            await warning.delete(delay=5)
            await self.bot.process_commands(message)
            return

        if not is_staff and config.get("anti_flood", True):
            tracker = self.bot.flood_tracker.setdefault(message.guild.id, {}).setdefault(message.author.id, [])
            now = datetime.now(timezone.utc).timestamp()
            tracker.append(now)
            window = config.get("flood_seconds", 5)
            limit = config.get("flood_limit", 5)
            self.bot.flood_tracker[message.guild.id][message.author.id] = [t for t in tracker if now - t <= window]
            if len(self.bot.flood_tracker[message.guild.id][message.author.id]) > limit:
                try:
                    await message.channel.set_permissions(message.author, send_messages=False)
                    mute_embed = discord.Embed(
                        description=f"{self.bot.custom_emojis['aviso']} {message.author.mention} fue silenciado por flood.",
                        color=self.bot.embed_color,
                    )
                    await message.channel.send(embed=mute_embed)
                except discord.Forbidden:
                    pass

        await self.bot.process_commands(message)

    @app_commands.command(name="bot-setup", description="Configura el bot: logs, roles de staff, automod.")
    @app_commands.checks.has_permissions(administrator=True)
    async def botsetup_command(self, interaction: discord.Interaction):
        existing = await self.bot.db.guild_config.find_one({"guild_id": interaction.guild_id})
        state = BotConfigState(interaction.guild_id, existing)
        view = BotSetupView(self.bot, state)
        embed = view.build_preview()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="giveaway-create", description="Crea un giveaway.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(duration="Ej: 30s, 5m, 2h, 1d, 1w", prize="Premio", winners="Cantidad de ganadores", description="Descripción opcional", channel="Canal donde se publica")
    async def giveaway_create(self, interaction: discord.Interaction, duration: str, prize: str, winners: int, channel: discord.TextChannel, description: str = ""):
        seconds = parse_time(duration)
        if seconds is None:
            await interaction.response.send_message("Formato de duración inválido. Usá 30s, 5m, 2h, 1d o 1w.", ephemeral=True)
            return
        ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        doc = {
            "guild_id": interaction.guild_id,
            "channel_id": channel.id,
            "prize": prize,
            "winners": winners,
            "description": description,
            "ends_at": ends_at,
            "status": "running",
            "participants": [],
            "host_id": interaction.user.id,
        }
        result = await self.bot.db.giveaways.insert_one(doc)
        embed = discord.Embed(
            title=f"🎉 {prize}",
            description=description or "¡Participá tocando el botón!",
            color=self.bot.embed_color,
        )
        embed.add_field(name="Ganadores", value=str(winners))
        embed.add_field(name="Termina", value=f"<t:{int(ends_at.timestamp())}:R>")
        embed.set_footer(text=self.bot.footer_text)
        view = GiveawayJoinView(str(result.inserted_id))
        msg = await channel.send(embed=embed, view=view)
        await self.bot.db.giveaways.update_one({"_id": result.inserted_id}, {"$set": {"message_id": msg.id}})
        await interaction.response.send_message(f"Giveaway creado en {channel.mention}.", ephemeral=True)

    @app_commands.command(name="giveaway-end", description="Finaliza un giveaway manualmente.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_end(self, interaction: discord.Interaction, giveaway_id: str):
        await interaction.response.defer(ephemeral=True)
        winners = await end_giveaway(self.bot, giveaway_id)
        await interaction.followup.send("Giveaway finalizado." if winners is not None else "No se encontró el giveaway.")

    @app_commands.command(name="giveaway-reroll", description="Vuelve a elegir ganador(es) de un giveaway.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, giveaway_id: str):
        await interaction.response.defer(ephemeral=True)
        winners = await end_giveaway(self.bot, giveaway_id, reroll=True)
        await interaction.followup.send("Reroll hecho." if winners is not None else "No se encontró el giveaway.")

    @app_commands.command(name="giveaway-list", description="Lista los giveaways activos.")
    async def giveaway_list(self, interaction: discord.Interaction):
        cursor = self.bot.db.giveaways.find({"guild_id": interaction.guild_id, "status": "running"})
        embed = discord.Embed(title="Giveaways activos", color=self.bot.embed_color)
        count = 0
        async for gw in cursor:
            count += 1
            embed.add_field(name=gw["prize"], value=f"ID: `{gw['_id']}` — Ganadores: {gw['winners']}", inline=False)
        if count == 0:
            embed.description = "No hay giveaways activos."
        embed.set_footer(text=self.bot.footer_text)
        await interaction.response.send_message(embed=embed)

    @tasks.loop(seconds=15)
    async def giveaway_checker(self):
        now = datetime.now(timezone.utc)
        cursor = self.bot.db.giveaways.find({"status": "running", "ends_at": {"$lte": now}})
        async for gw in cursor:
            await end_giveaway(self.bot, str(gw["_id"]))

    @giveaway_checker.before_loop
    async def before_checker(self):
        await self.bot.wait_until_ready()

    async def _log(self, guild: discord.Guild, embed: discord.Embed):
        config = self.bot.guild_config_cache.get(guild.id) or await self.bot.db.guild_config.find_one({"guild_id": guild.id})
        if config and config.get("log_channel_id"):
            channel = guild.get_channel(config["log_channel_id"])
            if channel:
                await channel.send(embed=embed)

    def _check_hierarchy(self, ctx, member: discord.Member) -> bool:
        return can_moderate(ctx.guild, ctx.author, member)

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send(f"{self.bot.custom_emojis['denegado']} {channel.mention} bloqueado.")

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await channel.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send(f"{self.bot.custom_emojis['aceptar']} {channel.mention} desbloqueado.")

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No especificada"):
        if not self._check_hierarchy(ctx, member):
            await ctx.send("No podés sancionar a alguien con un rol igual o superior al tuyo.")
            return
        await dm_sanction(self.bot, member, ctx.guild, "baneo", reason)
        await ctx.guild.ban(member, reason=reason)
        await ctx.send(f"{self.bot.custom_emojis['denegado']} {member} fue baneado. Razón: {reason}")

    @commands.command(name="tempban")
    @commands.has_permissions(ban_members=True)
    async def tempban(self, ctx, member: discord.Member, duration: str, *, reason: str = "No especificada"):
        if not self._check_hierarchy(ctx, member):
            await ctx.send("No podés sancionar a alguien con un rol igual o superior al tuyo.")
            return
        seconds = parse_time(duration)
        if seconds is None:
            await ctx.send("Formato de tiempo inválido. Usá 30s, 5m, 2h, 1d, 1w.")
            return
        await dm_sanction(self.bot, member, ctx.guild, "baneo temporal", reason, duration)
        await ctx.guild.ban(member, reason=reason)
        await self.bot.db.tempbans.insert_one({
            "guild_id": ctx.guild.id, "user_id": member.id,
            "unban_at": datetime.now(timezone.utc) + timedelta(seconds=seconds),
        })
        await ctx.send(f"{self.bot.custom_emojis['denegado']} {member} fue baneado temporalmente por {duration}.")

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int, *, reason: str = "No especificada"):
        try:
            await ctx.guild.unban(discord.Object(id=user_id), reason=reason)
            await ctx.send(f"{self.bot.custom_emojis['aceptar']} Usuario `{user_id}` desbaneado.")
        except discord.NotFound:
            await ctx.send("Ese usuario no está baneado.")

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No especificada"):
        if not self._check_hierarchy(ctx, member):
            await ctx.send("No podés sancionar a alguien con un rol igual o superior al tuyo.")
            return
        await dm_sanction(self.bot, member, ctx.guild, "expulsión", reason)
        await member.kick(reason=reason)
        await ctx.send(f"{self.bot.custom_emojis['denegado']} {member} fue expulsado. Razón: {reason}")

    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, duration: str, *, reason: str = "No especificada"):
        if not self._check_hierarchy(ctx, member):
            await ctx.send("No podés sancionar a alguien con un rol igual o superior al tuyo.")
            return
        seconds = parse_time(duration)
        if seconds is None:
            await ctx.send("Formato de tiempo inválido. Usá 30s, 5m, 2h, 1d, 1w.")
            return
        await member.timeout(timedelta(seconds=seconds), reason=reason)
        await dm_sanction(self.bot, member, ctx.guild, "mute", reason, duration)
        await ctx.send(f"{self.bot.custom_emojis['reloj']} {member} muteado por {duration}. Razón: {reason}")

    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member):
        await member.timeout(None)
        await ctx.send(f"{self.bot.custom_emojis['aceptar']} {member} desmuteado.")

    @commands.command(name="timeout")
    @commands.has_permissions(moderate_members=True)
    async def timeout_cmd(self, ctx, member: discord.Member, duration: str, *, reason: str = "No especificada"):
        await self.mute(ctx, member, duration, reason=reason)

    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No especificada"):
        if not self._check_hierarchy(ctx, member):
            await ctx.send("No podés sancionar a alguien con un rol igual o superior al tuyo.")
            return
        counter = await self.bot.db.counters.find_one_and_update(
            {"guild_id": ctx.guild.id, "type": "warn"}, {"$inc": {"value": 1}}, upsert=True, return_document=True
        )
        warn_id = counter["value"]
        await self.bot.db.warns.insert_one({
            "warn_id": warn_id, "guild_id": ctx.guild.id, "user_id": member.id,
            "reason": reason, "moderator_id": ctx.author.id, "created_at": datetime.now(timezone.utc),
        })
        await dm_sanction(self.bot, member, ctx.guild, "advertencia", reason)
        await ctx.send(f"{self.bot.custom_emojis['aviso']} {member} advertido (ID #{warn_id}). Razón: {reason}")

    @commands.command(name="warnings")
    async def warnings_cmd(self, ctx, member: discord.Member):
        cursor = self.bot.db.warns.find({"guild_id": ctx.guild.id, "user_id": member.id})
        embed = discord.Embed(title=f"Warns de {member}", color=self.bot.embed_color)
        count = 0
        async for w in cursor:
            count += 1
            embed.add_field(name=f"#{w['warn_id']}", value=w["reason"], inline=False)
        if count == 0:
            embed.description = "Este usuario no tiene advertencias."
        embed.set_footer(text=self.bot.footer_text)
        await ctx.send(embed=embed)

    @commands.command(name="delwarn")
    @commands.has_permissions(moderate_members=True)
    async def delwarn(self, ctx, member: discord.Member, warn_id: int):
        result = await self.bot.db.warns.delete_one({"guild_id": ctx.guild.id, "user_id": member.id, "warn_id": warn_id})
        if result.deleted_count:
            await ctx.send(f"{self.bot.custom_emojis['aceptar']} Warn #{warn_id} eliminado.")
        else:
            await ctx.send("No se encontró ese warn.")

    @commands.command(name="editreason")
    @commands.has_permissions(moderate_members=True)
    async def editreason(self, ctx, member: discord.Member, warn_id: int, *, new_reason: str):
        result = await self.bot.db.warns.update_one(
            {"guild_id": ctx.guild.id, "user_id": member.id, "warn_id": warn_id}, {"$set": {"reason": new_reason}}
        )
        if result.matched_count:
            await ctx.send(f"{self.bot.custom_emojis['aceptar']} Razón del warn #{warn_id} actualizada.")
        else:
            await ctx.send("No se encontró ese warn.")

    @commands.command(name="note")
    @commands.has_permissions(moderate_members=True)
    async def note(self, ctx, member: discord.Member, *, content: str):
        counter = await self.bot.db.counters.find_one_and_update(
            {"guild_id": ctx.guild.id, "type": "note"}, {"$inc": {"value": 1}}, upsert=True, return_document=True
        )
        note_id = counter["value"]
        await self.bot.db.notes.insert_one({
            "note_id": note_id, "guild_id": ctx.guild.id, "user_id": member.id,
            "content": content, "author_id": ctx.author.id, "created_at": datetime.now(timezone.utc),
        })
        await ctx.send(f"Nota #{note_id} agregada a {member}.")

    @commands.command(name="viewnotes")
    @commands.has_permissions(moderate_members=True)
    async def viewnotes(self, ctx, member: discord.Member):
        cursor = self.bot.db.notes.find({"guild_id": ctx.guild.id, "user_id": member.id})
        embed = discord.Embed(title=f"Notas de {member}", color=self.bot.embed_color)
        count = 0
        async for n in cursor:
            count += 1
            embed.add_field(name=f"#{n['note_id']}", value=n["content"], inline=False)
        if count == 0:
            embed.description = "Sin notas registradas."
        embed.set_footer(text=self.bot.footer_text)
        await ctx.send(embed=embed)

    @commands.command(name="delnote")
    @commands.has_permissions(moderate_members=True)
    async def delnote(self, ctx, member: discord.Member, note_id: int):
        result = await self.bot.db.notes.delete_one({"guild_id": ctx.guild.id, "user_id": member.id, "note_id": note_id})
        if result.deleted_count:
            await ctx.send(f"{self.bot.custom_emojis['aceptar']} Nota #{note_id} eliminada.")
        else:
            await ctx.send("No se encontró esa nota.")

    @commands.command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await channel.edit(slowmode_delay=seconds)
        await ctx.send(f"{self.bot.custom_emojis['reloj_arena']} Slowmode de {seconds}s aplicado en {channel.mention}.")

    @commands.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int):
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"{self.bot.custom_emojis['aceptar']} Se eliminaron {len(deleted) - 1} mensajes.")
        await msg.delete(delay=4)

    @commands.command(name="dm")
    @commands.has_permissions(manage_guild=True)
    async def dm_cmd(self, ctx, member: discord.Member, *, content: str):
        try:
            embed = discord.Embed(description=content, color=self.bot.embed_color)
            embed.set_footer(text=self.bot.footer_text)
            await member.send(embed=embed)
            await ctx.send(f"Mensaje enviado a {member}.")
        except discord.Forbidden:
            await ctx.send("No pude enviarle un DM a ese usuario.")

    @commands.command(name="addrole")
    @commands.has_permissions(manage_roles=True)
    async def addrole(self, ctx, member: discord.Member, role: discord.Role):
        await member.add_roles(role)
        await ctx.send(f"{self.bot.custom_emojis['aceptar']} Rol {role.mention} agregado a {member}.")

    @commands.command(name="removerole")
    @commands.has_permissions(manage_roles=True)
    async def removerole(self, ctx, member: discord.Member, role: discord.Role):
        await member.remove_roles(role)
        await ctx.send(f"{self.bot.custom_emojis['aceptar']} Rol {role.mention} removido de {member}.")

    @commands.command(name="nick")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, new_nick: str = None):
        await member.edit(nick=new_nick)
        await ctx.send(f"{self.bot.custom_emojis['aceptar']} Apodo de {member} actualizado.")

    @commands.command(name="userinfo")
    async def userinfo(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"Información de {member}", color=self.bot.embed_color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id)
        embed.add_field(name="Cuenta creada", value=discord.utils.format_dt(member.created_at, "R"))
        embed.add_field(name="Se unió", value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Desconocido")
        embed.add_field(name="Roles", value=" ".join(r.mention for r in member.roles[1:]) or "Ninguno", inline=False)
        embed.set_footer(text=self.bot.footer_text)
        await ctx.send(embed=embed)

    @commands.command(name="cmds")
    async def cmds(self, ctx):
        embed = discord.Embed(title="Comandos de Swimming for Animals", color=self.bot.embed_color)
        embed.add_field(
            name="Moderación",
            value="lock, unlock, ban, tempban, unban, kick, mute, unmute, timeout, warn, warnings, delwarn, editreason, note, viewnotes, delnote, slowmode, clear",
            inline=False,
        )
        embed.add_field(name="Utilidad", value="dm, addrole, removerole, nick, userinfo, cmds", inline=False)
        embed.add_field(name="Tickets", value="adduser, removeuser, close, delete, rename", inline=False)
        embed.set_footer(text=self.bot.footer_text)
        await ctx.send(embed=embed)

    @tasks.loop(seconds=30)
    async def tempban_checker(self):
        now = datetime.now(timezone.utc)
        cursor = self.bot.db.tempbans.find({"unban_at": {"$lte": now}})
        async for t in cursor:
            guild = self.bot.get_guild(t["guild_id"])
            if guild:
                try:
                    await guild.unban(discord.Object(id=t["user_id"]), reason="Fin de tempban")
                except discord.NotFound:
                    pass
            await self.bot.db.tempbans.delete_one({"_id": t["_id"]})

    @tempban_checker.before_loop
    async def before_tempban_checker(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    cog = BotCommands(bot)
    await bot.add_cog(cog)
    cog.tempban_checker.start()
