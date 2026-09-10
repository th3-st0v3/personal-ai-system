from calculations import (
    hydrostatic_pressure_record,
    darcy_weisbach_pressure_loss_record,
)
from db import (
    add_note,
    get_notes,
    search_notes,
    create_project,
    get_projects,
    create_requirement,
    get_requirement,
    add_evidence,
    get_evidence_for_requirement,
    get_evidence_history_for_requirement,
    find_matching_evidence,
    update_requirement_status,
    evaluate_requirement_evidence,
    invalidate_evidence,
    save_calculation_record,
    get_recent_calculation_records,
)


STATUS_CHOICES = {
    "1": "Verified",
    "2": "Failed",
    "3": "Unverified",
    "4": "At risk",
}


def run_hydrostatic_calculation():
    density = float(input("Density (kg/m^3): "))
    gravity = float(input("Gravity (m/s^2): "))
    depth = float(input("Depth (m): "))

    record = hydrostatic_pressure_record(
        density_kg_m3=density,
        gravity_m_s2=gravity,
        depth_m=depth,
    )

    save_calculation_record(record)

    print(f"Pressure: {record.result} {record.result_unit}")
    return record


def run_darcy_weisbach_calculation():
    friction_factor = float(input("Friction factor: "))
    pipe_length = float(input("Pipe length (m): "))
    pipe_diameter = float(input("Pipe diameter (m): "))
    density = float(input("Density (kg/m^3): "))
    velocity = float(input("Velocity (m/s): "))

    record = darcy_weisbach_pressure_loss_record(
        friction_factor=friction_factor,
        pipe_length_m=pipe_length,
        pipe_diameter_m=pipe_diameter,
        density_kg_m3=density,
        velocity_m_s=velocity,
    )

    save_calculation_record(record)

    print(f"Pressure loss: {record.result} {record.result_unit}")
    return record


def run_recent_calculations():
    records = get_recent_calculation_records(10)

    if not records:
        print("No calculations saved.")
        return

    for index, record in enumerate(records, start=1):
        print(
            f"{index}. {record.calculation_type}: "
            f"{record.result} {record.result_unit}"
        )


def notes_menu():
    while True:
        print("Notes")
        print("────────────────────────")
        print("1. Add a note")
        print("2. View notes")
        print("3. Search notes")
        print("4. Back")

        choice = input("Choose an option: ")

        if choice == "1":
            note = input("Enter a note: ")
            add_note(note)
            print("Note saved.")

        elif choice == "2":
            notes = get_notes()
            print("\nYour notes:")

            for note in notes:
                print(f"{note[0]}. {note[1]}")
                print(f"   {note[3]}")

        elif choice == "3":
            query = input("Search for: ")
            notes = search_notes(query)

            print("\nSearch results:")

            for note in notes:
                print(f"{note[0]}. {note[1]}")
                print(f"   {note[3]}")

        elif choice == "4":
            break

        else:
            print("Invalid option. Please choose 1-4.")


def projects_menu():
    while True:
        print("Projects")
        print("────────────────────────")
        print("1. Create project")
        print("2. List projects")
        print("3. Back")

        choice = input("Choose an option: ")

        if choice == "1":
            name = input("Project name: ")
            description = input("Description (optional): ") or None
            project_id = create_project(name, description)
            print(f"Project created with id {project_id}.")

        elif choice == "2":
            projects = get_projects()
            print("\nProjects:")

            for project in projects:
                print(
                    f"{project[0]}. "
                    f"{project[1]} - {project[2] or ''}"
                )

        elif choice == "3":
            break

        else:
            print("Invalid option. Please choose 1-3.")


def requirements_menu():
    while True:
        print("Requirements")
        print("────────────────────────")
        print("1. Create requirement")
        print("2. View requirement")
        print("3. Update requirement status")
        print("4. Evaluate requirement evidence")
        print("5. View evidence history")
        print("6. Back")

        choice = input("Choose an option: ")

        if choice == "1":
            try:
                project_id = int(input("Project id: "))
            except ValueError:
                print("Project id must be a number.")
            else:
                description = input("Requirement description: ")
                requirement_id = create_requirement(
                    project_id,
                    description,
                )
                print(
                    f"Requirement created with id {requirement_id}."
                )

        elif choice == "2":
            try:
                requirement_id = int(input("Requirement id: "))
            except ValueError:
                print("Requirement id must be a number.")
            else:
                requirement = get_requirement(requirement_id)

                if requirement is None:
                    print("No requirement with that id.")
                else:
                    print(
                        f"\nRequirement {requirement[0]}: "
                        f"{requirement[3]}"
                    )
                    print(f"Project: {requirement[2]}")
                    print(f"Status: {requirement[4]}")

                    evidence = get_evidence_for_requirement(
                        requirement_id
                    )

                    print("Evidence:")

                    if not evidence:
                        print("  (no evidence recorded yet)")

                    for item in evidence:
                        loc = item[3] or "no location given"
                        print(
                            f"  - [{item[5]}] {item[2]} "
                            f"({loc}): {item[4]}"
                        )

        elif choice == "3":
            try:
                requirement_id = int(input("Requirement id: "))
            except ValueError:
                print("Requirement id must be a number.")
            else:
                print("Set status to:")
                print("1. Verified")
                print("2. Failed")
                print("3. Unverified")
                print("4. At risk")

                new_status = STATUS_CHOICES.get(
                    input("Choose 1-4: ")
                )

                if new_status is None:
                    print("Invalid choice, status not changed.")
                else:
                    update_requirement_status(
                        requirement_id,
                        new_status,
                    )
                    print(
                        f"Requirement {requirement_id} "
                        f"status set to {new_status}."
                    )

        elif choice == "4":
            try:
                requirement_id = int(input("Requirement id: "))
            except ValueError:
                print("Requirement id must be a number.")
            else:
                requirement = get_requirement(requirement_id)

                if requirement is None:
                    print("No requirement with that id.")
                else:
                    evaluation = evaluate_requirement_evidence(
                        requirement_id
                    )

                    print(
                        f"\nRequirement {requirement[0]}: "
                        f"{requirement[3]}"
                    )
                    print(f"Current status: {requirement[4]}")
                    print(
                        "Evidence assessment: "
                        f"{evaluation['recommendation']}"
                    )

                    signals = evaluation["signals"]

                    if signals:
                        print(
                            "Evidence signals: "
                            f"{', '.join(signals)}"
                        )
                    else:
                        print("Evidence signals: none")

                    print(
                        "Conflict: "
                        f"{'Yes' if evaluation['conflict'] else 'No'}"
                    )

                    if evaluation["conflict"]:
                        print(
                            "Review conflicting evidence before "
                            "changing the requirement status."
                        )

        elif choice == "5":
            try:
                requirement_id = int(input("Requirement id: "))
            except ValueError:
                print("Requirement id must be a number.")
            else:
                requirement = get_requirement(requirement_id)

                if requirement is None:
                    print("No requirement with that id.")
                else:
                    history = get_evidence_history_for_requirement(
                        requirement_id
                    )

                    print(
                        f"\nEvidence history for requirement "
                        f"{requirement[0]}: {requirement[3]}"
                    )

                    if not history:
                        print(
                            "  (no evidence history recorded yet)"
                        )

                    for item in history:
                        loc = item[3] or "no location given"
                        print(
                            f"  - [{item[5]}] {item[2]} "
                            f"({loc}): {item[4]} "
                            f"[{item[6]}] at {item[7]}"
                        )

        elif choice == "6":
            break

        else:
            print("Invalid option. Please choose 1-6.")


def evidence_menu():
    while True:
        print("Evidence")
        print("────────────────────────")
        print("1. Add evidence")
        print("2. Invalidate evidence")
        print("3. Back")

        choice = input("Choose an option: ")

        if choice == "1":
            try:
                requirement_id = int(input("Requirement id: "))
            except ValueError:
                print("Requirement id must be a number.")
                continue

            source = input(
                "Evidence source (e.g. test log, datasheet): "
            )
            location = input(
                "Location (page/section/timestamp, optional): "
            ) or None
            result = input("What did the evidence show?: ")

            print("Does this evidence support:")
            print("1. Verified")
            print("2. Failed")
            print("3. Unverified")
            print("4. At risk")

            supports_status = STATUS_CHOICES.get(
                input("Choose 1-4: ")
            )

            if supports_status is None:
                print("Invalid choice, evidence not saved.")
                continue

            matches = find_matching_evidence(
                requirement_id,
                source,
                result,
                supports_status,
                location,
            )

            save_evidence = True

            if matches:
                print("\nWarning: matching evidence already exists:")

                for item in matches:
                    loc = item[3] or "no location given"
                    print(
                        f"  - [{item[5]}] {item[2]} "
                        f"({loc}): {item[4]}"
                    )

                answer = input(
                    "Save this evidence anyway? (y/n): "
                )
                save_evidence = answer.strip().lower() == "y"

            if save_evidence:
                add_evidence(
                    requirement_id,
                    source,
                    result,
                    supports_status,
                    location,
                )
                print("Evidence saved.")
            else:
                print("Evidence not saved.")

        elif choice == "2":
            try:
                evidence_id = int(
                    input("Evidence ID to invalidate: ")
                )
                invalidate_evidence(evidence_id)
                print(
                    f"Evidence {evidence_id} invalidated."
                )
            except ValueError as error:
                print(f"Error: {error}")

        elif choice == "3":
            break

        else:
            print("Invalid option. Please choose 1-3.")


def calculations_menu():
    while True:
        print("Calculations")
        print("────────────────────────")
        print("1. Run hydrostatic calculation")
        print("2. Run Darcy-Weisbach calculation")
        print("3. View recent calculations")
        print("4. Back")
        choice = input("Choose an option: ")

        if choice == "1":
            run_hydrostatic_calculation()

        elif choice == "2":
            run_darcy_weisbach_calculation()

        elif choice == "3":
            run_recent_calculations()

        elif choice == "4":
            break

        else:
            print("Invalid option. Please choose 1-4.")


def ask_ai():
    try:
        from model import ask_model
    except ImportError as error:
        print(f"\nAI feature unavailable: {error}")
        return

    prompt = input("Ask the AI: ")

    try:
        answer = ask_model(prompt)
        print("\nAI:")
        print(answer)
    except Exception as error:
        print(f"\nAI request failed: {error}")


def main():
    while True:
        print("Personal AI System")
        print("────────────────────────")
        print("1. Notes")
        print("2. Projects")
        print("3. Requirements")
        print("4. Evidence")
        print("5. Calculations")
        print("6. Ask AI")
        print("7. Quit")

        choice = input("Choose an option: ")

        if choice == "1":
            notes_menu()

        elif choice == "2":
            projects_menu()

        elif choice == "3":
            requirements_menu()

        elif choice == "4":
            evidence_menu()

        elif choice == "5":
            calculations_menu()

        elif choice == "6":
            ask_ai()

        elif choice == "7":
            print("Goodbye.")
            break

        else:
            print("Invalid option. Please choose 1-7.")


if __name__ == "__main__":
    main()
