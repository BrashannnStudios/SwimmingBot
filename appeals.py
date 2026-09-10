import discord
from discord import app_commands
from discord.ext import commands

APPEAL_BUTTON_CUSTOM_ID = "dbb_appeal_start"
DEFAULT_QUESTIONS = [
    "¿Por qué creés que fuiste sancionado?",
    "¿Por qué debería levantarse tu sanción?",
]

# Estado temporal del flujo de apelación por usuario mientras completa el proceso
_pending_appeals: dict[int, dict] = {}


class AppealConfigState:
    def __init__(self, guild_id: int, existing: dict | None):
        self.guild_id = guild_id
        self.staff_channel_id = existing.get("staff_channel_id") if existing else None
        self.questions = existing.get("questions", list(DEFAULT_QUESTIONS)) if existing else list(DEFAULT_QUESTIONS)


class QuestionsModal(discord.ui.Modal, title="Preguntas del formulario"):
    def __init__(self, view: "AppealSetupView"):
        super().__init__()
        self.view_ref = view
        self.questions_input = discord.ui.TextInput(
            label="Una pregunta por línea (máx. 5)",
            style=discord.TextStyle.paragraph,
            default="\n".join(view.state.questions),
            max_length=500,
        )
        self.add_item(self.questions_input)

    async def on_submit(self, interaction: discord.Interaction):
        qs = [q.strip() for q in self.questions_input.value.split("\n") if q.strip()][:5]
        if qs:
            self.view_ref.state.questions = qs
        await self.view_ref.refresh(interaction)


class AppealStaffChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "AppealSetupView"):
        super().__init__(
            placeholder="Canal donde llegan las solicitudes de apelación",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.staff_channel_id = self.values[0].id
        await self.view_ref.refresh(interaction)


class AppealSetupView(discord.ui.View):
    def __init__(self, bot, state: AppealConfigState):
        super().__init__(timeout=600)
        self.bot = bot
        self.state = state
        self.add_item(AppealStaffChannelSelect(self))

    def build_preview(self) -> discord.Embed:
        embed = discord.Embed(
            title="Vista previa — Configuración de Apelaciones",
            color=self.bot.embed_color,
        )
        embed.add_field(
            name="Canal de staff",
            value=f"<#{self.state.staff_channel_id}>" if self.state.staff_channel_id else "No configurado",
            inline=False,
        )
        embed.add_field(
            name="Preguntas del formulario",
            value="\n".join(f"{i+1}. {q}" for i, q in enumerate(self.state.questions)),
            inline=False,
        )
        embed.set_footer(text=self.bot.footer_text)
        return embed

    async def refresh(self, interaction: discord.Interaction):
        embed = self.build_preview()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Editar preguntas", style=discord.ButtonStyle.secondary, row=2)
    async def edit_questions(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QuestionsModal(self))

    @discord.ui.button(label="Guardar", style=discord.ButtonStyle.success, row=2)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.state.staff_channel_id:
            await interaction.response.send_message("Elegí un canal de staff antes de guardar.", ephemeral=True)
            return
        data = {"staff_channel_id": self.state.staff_channel_id, "questions": self.state.questions}
        await self.bot.db.appeal_config.update_one(
            {"guild_id": self.state.guild_id}, {"$set": data}, upsert=True
        )
        embed = discord.Embed(
            description=f"{self.bot.emojis['aceptar']} Configuración de apelaciones guardada.",
            color=self.bot.embed_color,
        )
        embed.set_footer(text=self.bot.footer_text)
        await interaction.response.edit_message(embed=embed, view=None)


class AppealQuestionsModal(discord.ui.Modal):
    def __init__(self, questions: list[str], guild_id: int, banned_user_id: int):
        super().__init__(title="Formulario de apelación")
        self.guild_id = guild_id
        self.banned_user_id = banned_user_id
        self.inputs = []
        for q in questions[:5]:
            ti = discord.ui.TextInput(label=q[:45], style=discord.TextStyle.paragraph, max_length=500)
            self.inputs.append(ti)
            self.add_item(ti)

    async def on_submit(self, interaction: discord.Interaction):
        answers = {ti.label: ti.value for ti in self.inputs}
        _pending_appeals[self.banned_user_id] = {
            "guild_id": self.guild_id,
            "answers": answers,
            "evidence": [],
        }
        embed = discord.Embed(
            description="¿Contás con evidencia para tu apelación?",
            color=interaction.client.embed_color,
        )
        await interaction.response.send_message(embed=embed, view=EvidenceChoiceView(), ephemeral=True)


class EvidenceChoiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Sí", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Adjuntá tus evidencias en este DM (imágenes o archivos). Cuando termines, tocá **Enviar solicitud**.",
            view=SendRequestView(waiting_evidence=True),
            ephemeral=True,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await submit_appeal(interaction)


class SendRequestView(discord.ui.View):
    def __init__(self, waiting_evidence: bool):
        super().__init__(timeout=600)
        self.waiting_evidence = waiting_evidence

    @discord.ui.button(label="¿Enviar solicitud?", style=discord.ButtonStyle.success)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button):
        await submit_appeal(interaction)


async def submit_appeal(interaction: discord.Interaction):
    bot = interaction.client
    user_id = interaction.user.id
    pending = _pending_appeals.get(user_id)
    if not pending:
        await interaction.response.send_message("No hay una apelación en curso.", ephemeral=True)
        return

    config = await bot.db.appeal_config.find_one({"guild_id": pending["guild_id"]})
    if not config or not config.get("staff_channel_id"):
        await interaction.response.send_message(
            "El sistema de apelaciones no está configurado en ese servidor.", ephemeral=True
        )
        return

    guild = bot.get_guild(pending["guild_id"])
    staff_channel = guild.get_channel(config["staff_channel_id"]) if guild else None
    if not staff_channel:
        await interaction.response.send_message("No se encontró el canal de staff.", ephemeral=True)
        return

    doc = {
        "guild_id": pending["guild_id"],
        "user_id": user_id,
        "answers": pending["answers"],
        "evidence": pending.get("evidence", []),
        "status": "pending",
    }
    result = await bot.db.appeals.insert_one(doc)

    embed = discord.Embed(
        title="📩 Nueva solicitud de apelación",
        color=bot.embed_color,
    )
    embed.add_field(name="Usuario", value=f"<@{user_id}> (`{user_id}`)", inline=False)
    for q, a in pending["answers"].items():
        embed.add_field(name=q, value=a[:1024], inline=False)
    if pending.get("evidence"):
        embed.add_field(name="Evidencias", value="\n".join(pending["evidence"][:10]), inline=False)
    embed.set_footer(text=bot.footer_text)

    view = AppealReviewView(str(result.inserted_id))
    await staff_channel.send(embed=embed, view=view)

    _pending_appeals.pop(user_id, None)

    confirm = discord.Embed(
        description=f"{bot.emojis['aceptar']} Tu solicitud de apelación fue enviada correctamente.",
        color=bot.embed_color,
    )
    if interaction.response.is_done():
        await interaction.followup.send(embed=confirm, ephemeral=True)
    else:
        await interaction.response.send_message(embed=confirm, ephemeral=True)


class AppealReviewView(discord.ui.View):
    def __init__(self, appeal_id: str):
        super().__init__(timeout=None)
        self.appeal_id = appeal_id
        self.accept.custom_id = f"dbb_appeal_accept:{appeal_id}"
        self.deny.custom_id = f"dbb_appeal_deny:{appeal_id}"
        self.thread.custom_id = f"dbb_appeal_thread:{appeal_id}"

    @discord.ui.button(label="Aceptar apelación", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        from bson import ObjectId
        bot = interaction.client
        appeal = await bot.db.appeals.find_one({"_id": ObjectId(self.appeal_id)})
        if not appeal:
            await interaction.response.send_message("Apelación no encontrada.", ephemeral=True)
            return
        guild = interaction.guild
        try:
            await guild.unban(discord.Object(id=appeal["user_id"]), reason="Apelación aceptada")
        except discord.NotFound:
            pass
        await bot.db.appeals.update_one({"_id": ObjectId(self.appeal_id)}, {"$set": {"status": "accepted"}})
        await interaction.response.send_message(f"Apelación aceptada por {interaction.user.mention}. Usuario desbaneado.")

    @discord.ui.button(label="Denegar apelación", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        from bson import ObjectId
        bot = interaction.client
        await bot.db.appeals.update_one({"_id": ObjectId(self.appeal_id)}, {"$set": {"status": "denied"}})
        await interaction.response.send_message(f"Apelación denegada por {interaction.user.mention}.")

    @discord.ui.button(label="Abrir Hilo", style=discord.ButtonStyle.secondary)
    async def thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = await interaction.channel.create_thread(
            name=f"apelacion-{self.appeal_id[-6:]}", message=interaction.message
        )
        await interaction.response.send_message(f"Hilo creado: {thread.mention}", ephemeral=True)


class AppealStartButton(discord.ui.View):
    """Se adjunta al DM de baneo."""

    def __init__(self, guild_id: int, banned_user_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.banned_user_id = banned_user_id
        self.start.custom_id = f"{APPEAL_BUTTON_CUSTOM_ID}:{guild_id}:{banned_user_id}"

    @discord.ui.button(label="Apelar baneo", style=discord.ButtonStyle.primary, emoji="📝")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        config = await bot.db.appeal_config.find_one({"guild_id": self.guild_id})
        questions = config["questions"] if config else DEFAULT_QUESTIONS
        await interaction.response.send_modal(
            AppealQuestionsModal(questions, self.guild_id, self.banned_user_id)
        )


class Appeals(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        active = self.bot.db.appeals.find({"status": "pending"})
        async for a in active:
            self.bot.add_view(AppealReviewView(str(a["_id"])))

    @app_commands.command(name="apelaciones-setup", description="Configura el sistema de apelaciones de baneos.")
    @app_commands.checks.has_permissions(administrator=True)
    async def apelaciones_setup(self, interaction: discord.Interaction):
        existing = await self.bot.db.appeal_config.find_one({"guild_id": interaction.guild_id})
        state = AppealConfigState(interaction.guild_id, existing)
        view = AppealSetupView(self.bot, state)
        embed = view.build_preview()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Captura evidencias adjuntadas en DM mientras el usuario está en proceso de apelación
        if message.guild is not None or message.author.bot:
            return
        pending = _pending_appeals.get(message.author.id)
        if pending is None:
            return
        for att in message.attachments:
            pending["evidence"].append(att.url)
        if pending["evidence"]:
            await message.channel.send(
                "Evidencia recibida. Podés seguir mandando más o tocar **¿Enviar solicitud?** cuando termines."
            )


async def setup(bot):
    await bot.add_cog(Appeals(bot))
