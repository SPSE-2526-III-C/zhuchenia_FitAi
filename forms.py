from flask_wtf import FlaskForm

from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    SelectField
)

from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length
)


class RegistrationForm(FlaskForm):

    username = StringField(
        'Username',
        validators=[
            DataRequired(message="Zadaj používateľské meno."),
            Length(min=3, max=20, message="Meno musí mať 3 až 20 znakov.")
        ]
    )

    email = StringField(
        'Email',
        validators=[
            DataRequired(message="Zadaj email."),
            Email(message="Zadaj platný email.")
        ]
    )

    password = PasswordField(
        'Password',
        validators=[
            DataRequired(message="Zadaj heslo."),
            Length(min=6, message="Heslo musí mať aspoň 6 znakov.")
        ]
    )

    confirm_password = PasswordField(
        'Confirm Password',
        validators=[
            DataRequired(message="Potvrď heslo."),
            EqualTo('password', message="Potvrdené heslo sa nezhoduje.")
        ]
    )

    submit = SubmitField('Register')


class LoginForm(FlaskForm):

    email = StringField(
        'Email',
        validators=[
            DataRequired(message="Zadaj email."),
            Email(message="Zadaj platný email.")
        ]
    )

    password = PasswordField(
        'Password',
        validators=[
            DataRequired(message="Zadaj heslo.")
        ]
    )

    submit = SubmitField('Login')


class WorkoutForm(FlaskForm):

    exercise = StringField(
        'Exercise',
        validators=[
            DataRequired()
        ]
    )

    weight = StringField(
        'Weight',
        validators=[
            DataRequired()
        ]
    )

    reps = StringField(
        'Reps',
        validators=[
            DataRequired()
        ]
    )

    workout_type = SelectField(
        'Workout Type',
        choices=[
            ('Push', 'Push'),
            ('Pull', 'Pull'),
            ('Legs', 'Legs'),
            ('Full Body', 'Full Body'),
            ('Calisthenics', 'Calisthenics')
        ]
    )

    submit = SubmitField('Add Workout')
