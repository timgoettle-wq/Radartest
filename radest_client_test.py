from radest.client import RadEstClient


def main():

    radest = RadEstClient()

    try:
        radest.connect()

        print("RadEsT verbunden")

        # Testwerte
        radest.set_distance(5.0)

        distance = radest.get_distance()

        print(
            f"Distanz RadEsT: {distance:.2f} m"
        )

        radest.set_velocity(
            0.0,
            towards=True
        )

        radest.set_rcs(
            20.0
        )

        print("Testwerte gesetzt")

    finally:
        radest.disconnect()

        print("RadEsT getrennt")


if __name__ == "__main__":
    main()