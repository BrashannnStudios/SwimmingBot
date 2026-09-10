import discord
from discord import app_commands
from discord.ext import commands

DEFAULT_MESSAGE = "¡Bienvenido/a {user} a **{server}**! Ahora somos {membercount} miembros."


def build_welcome_embed(bot, config: dict, member: discord.Member) -> discord.Embed:
    msg = config.get("message", DEFAULT_MESSAGE)
    msg = (
        msg.replace("{user}", member.mention)
        .replace("{username}", member.name)
        .replace("{server}", member.guild.name)
        .replace("{membercount}", str(member.guild.member_count))
    )
    color = config.get("color", bot.embed_color)
    embed = discord.Embed(description=msg, color=color)
    embed.set_footer(text=config.get("footer", bot.footer_text))
    if config.get("image"):
        embed.set_image(url=config["image"])
    embed.set_thumbnail(url=member.display_avatar.url)
    return embed


class WelcomeConfigState:
    """Estado temporal mientras el staff configura el panel de bienvenida."""

    def __init__(self, guild_id: int, existing: dict | None):
        self.guild_id = guild_id
        self.channel_id = existing.get("channel_id") if existing else None
        self.message = existing.get("message", DEFAULT_MESSAGE) if existing else DEFAULT_MESSAGE
        self.color = existing.get("color") if existing else None
        self.footer = existing.get("footer") if existing else None
        self.image = existing.get("image") if existing else None
        self.recommended_channels = existing.get("recommended_channels", []) if existing else []


class MessageModal(discord.ui.Modal, title="Mensaje de bienvenida"):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view
        self.message_input = discord.ui.TextInput(
            label="Mensaje (usa {user} {username} {server} {membercount})",
            style=discord.TextStyle.paragraph,
            default=view.state.message,
            max_length=1000,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.state.message = self.message_input.value
        await self.view_ref.refresh(interaction)


class ColorModal(discord.ui.Modal, title="Color del embed"):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view
        self.color_input = discord.ui.TextInput(
            label="Color en hexadecimal (ej: #cef3f1)",
            required=False,
            max_length=7,
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.color_input.value.strip()
        if value:
            try:
                self.view_ref.state.color = int(value.replace("#", ""), 16)
            except ValueError:
                await interaction.response.send_message(
                    "Color inválido, usá formato hexadecimal (#cef3f1).", ephemeral=True
                )
                return
        await self.view_ref.refresh(interaction)


class FooterModal(discord.ui.Modal, title="Footer del embed"):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view
        self.footer_input = discord.ui.TextInput(
            label="Texto del footer", required=False, max_length=200,
            default=view.state.footer or "",
        )
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.state.footer = self.footer_input.value or None
        await self.view_ref.refresh(interaction)


class ImageModal(discord.ui.Modal, title="Imagen del embed"):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view
        self.image_input = discord.ui.TextInput(
            label="URL de la imagen", required=False, max_length=500,
            default=view.state.image or "",
        )
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.state.image = self.image_input.value or None
        await self.view_ref.refresh(interaction)


class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__(
            placeholder="Canal de bienvenida",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.channel_id = self.values[0].id
        await self.view_ref.refresh(interaction)


class RecommendedChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__(
            placeholder="Canales recomendados (opcional)",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=10,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.recommended_channels = [c.id for c in self.values]
        await self.view_ref.refresh(interaction)


class WelcomeSetupView(discord.ui.View):
    def __init__(self, bot, state: WelcomeConfigState):
        super().__init__(timeout=600)
        self.bot = bot
        self.state = state
        self.add_item(WelcomeChannelSelect(self))
        self.add_item(RecommendedChannelsSelect(self))

    def build_preview_embed(self, guild: discord.Guild) -> discord.Embed:
        color = self.state.color or self.bot.embed_color
        preview = (
            self.state.message.replace("{user}", "@Usuario")
            .replace("{username}", "Usuario")
            .replace("{server}", guild.name)
            .replace("{membercount}", str(guild.member_count))
        )
        embed = discord.Embed(
            title="Vista previa — Configuración de Bienvenida",
            description=preview,
            color=color,
        )
        embed.add_field(
            name="Canal",
            value=f"<#{self.state.channel_id}>" if self.state.channel_id else "No configurado",
        )
        if self.state.image:
            embed.set_image(url=self.state.image)
        embed.set_footer(text=self.state.footer or self.bot.footer_text)
        return embed

    async def refresh(self, interaction: discord.Interaction):
        embed = self.build_preview_embed(interaction.guild)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Editar mensaje", style=discord.ButtonStyle.secondary, row=2)
    async def edit_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MessageModal(self))

    @discord.ui.button(label="Editar color", style=discord.ButtonStyle.secondary, row=2)
    async def edit_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ColorModal(self))

    @discord.ui.button(label="Editar footer", style=discord.ButtonStyle.secondary, row=2)
    async def edit_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FooterModal(self))

    @discord.ui.button(label="Editar imagen", style=discord.ButtonStyle.secondary, row=3)
    async def edit_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ImageModal(self))

    @discord.ui.button(label="Guardar", style=discord.ButtonStyle.success, row=3)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.state.channel_id:
            await interaction.response.send_message(
                "Tenés que elegir un canal antes de guardar.", ephemeral=True
            )
            return
        data = {
            "channel_id": self.state.channel_id,
            "message": self.state.message,
            "color": self.state.color,
            "footer": self.state.footer,
            "image": self.state.image,
            "recommended_channels": self.state.recommended_channels,
        }
        await self.bot.db.welcome_config.update_one(
            {"guild_id": self.state.guild_id}, {"$set": data}, upsert=True
        )
        embed = discord.Embed(
            description=f"{self.bot.emojis['aceptar']} Configuración de bienvenida guardada correctamente.",
            color=self.bot.embed_color,
        )
        embed.set_footer(text=self.bot.footer_text)
        await interaction.response.edit_message(embed=embed, view=None)


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="welcome-setup", description="Configura el sistema de bienvenidas del servidor.")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_setup(self, interaction: discord.Interaction):
        existing = await self.bot.db.welcome_config.find_one({"guild_id": interaction.guild_id})
        state = WelcomeConfigState(interaction.guild_id, existing)
        view = WelcomeSetupView(self.bot, state)
        embed = view.build_preview_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self.bot.db.welcome_config.find_one({"guild_id": member.guild.id})
        if not config or not config.get("channel_id"):
            return
        channel = member.guild.get_channel(config["channel_id"])
        if not channel:
            return
        embed = build_welcome_embed(self.bot, config, member)
        view = None
        recs = config.get("recommended_channels") or []
        if recs:
            view = discord.ui.View()
            for cid in recs[:5]:
                ch = member.guild.get_channel(cid)
                if ch:
                    view.add_item(
                        discord.ui.Button(label=f"#{ch.name}", style=discord.ButtonStyle.link, url=ch.jump_url)
                    )
        await channel.send(content=member.mention, embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
